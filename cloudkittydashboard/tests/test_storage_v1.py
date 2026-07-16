# Copyright 2026 Cloudification GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import decimal
import importlib
import os
from types import SimpleNamespace
import unittest
from unittest import mock

import django
from django.template import Context
from django.template.loader import get_template
from horizon import loaders

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'openstack_dashboard.settings')
django.setup()

summary = importlib.import_module(
    'cloudkittydashboard.dashboards.admin.summary.views')
reporting = importlib.import_module(
    'cloudkittydashboard.dashboards.project.reporting.views')
raw_usage = importlib.import_module(
    'cloudkittydashboard.dashboards.project.raw_usage.views')


class SummaryStorageVersionTests(unittest.TestCase):

    def test_details_template_owns_groupby_partial(self):
        template_dir = os.path.join(
            os.path.dirname(summary.__file__), 'templates')
        panel_dirs = {'admin/rating_summary': template_dir}

        with mock.patch.dict(loaders.panel_template_dirs, panel_dirs,
                             clear=True):
            template = get_template(
                'admin/rating_summary/details.html').template
            context = Context({
                'project_id': 'project-1',
                'groupby_list': ['type'],
            })
            with context.bind_template(template):
                output = template.nodelist[0].blocks['main'].render(context)

        self.assertIn('groupby_checkbox', output)

    @mock.patch.object(summary.api_keystone, 'tenant_list')
    @mock.patch.object(summary.api, 'cloudkittyclient')
    def test_index_uses_v1_report_api(self, client_factory, tenant_list):
        client = client_factory.return_value
        client.report.get_summary.return_value = {
            'summary': [{'tenant_id': 'project-1', 'rate': '2.5'}]
        }
        tenant_list.return_value = (
            [SimpleNamespace(id='project-1', name='Project 1')], None)

        view = summary.IndexView()
        view.request = mock.Mock()
        settings = SimpleNamespace(OPENSTACK_CLOUDKITTY_STORAGE_VERSION=1)
        with mock.patch.object(summary, 'settings', settings):
            data = view.get_data()

        client_factory.assert_called_once_with(view.request)
        client.report.get_summary.assert_called_once_with(
            groupby=['tenant_id'], all_tenants=True)
        self.assertEqual('Project 1', data[0]['name'])
        self.assertEqual('2.50', data[0]['rate'])
        self.assertEqual('Cloud Total', data[1]['name'])


class ReportingStorageVersionTests(unittest.TestCase):

    def test_raw_usage_template_requires_filters_before_table(self):
        raw_usage_template_dir = os.path.join(
            os.path.dirname(raw_usage.__file__), 'templates')
        reporting_template_dir = os.path.join(
            os.path.dirname(reporting.__file__), 'templates')
        panel_dirs = {
            'project/raw_usage': raw_usage_template_dir,
            'project/reporting': reporting_template_dir,
        }
        form = raw_usage.forms.RawUsageFilterForm(initial={
            'start': '2026-07-01',
            'end': '2026-07-16',
        }, resource_types=['instance'])

        with mock.patch.dict(loaders.panel_template_dirs, panel_dirs,
                             clear=True):
            template = get_template('project/raw_usage/index.html').template
            context = Context({
                'form': form,
                'queried': False,
                'usage_rows': [],
            })
            with context.bind_template(template):
                output = template.nodelist[0].blocks['main'].render(context)

        self.assertIn('Select a resource type', output)
        self.assertNotIn('No usage data available', output)

    def test_v1_storage_setting(self):
        settings = SimpleNamespace(OPENSTACK_CLOUDKITTY_STORAGE_VERSION=1)
        with mock.patch.object(reporting, 'settings', settings):
            self.assertTrue(reporting._uses_v1_storage())

    def test_build_v1_reporting_data(self):
        data = {
            'dataframes': [
                {
                    'begin': '2026-07-16T10:00:00',
                    'resources': [
                        {'service': 'cpu', 'rating': '1.25'},
                        {'service': 'volume', 'rating': '2'},
                    ],
                },
                {
                    'begin': '2026-07-16T12:00:00',
                    'resources': [
                        {'service': 'cpu', 'rating': '0.75'},
                    ],
                },
            ],
        }

        result = reporting._build_reporting_data_v1(data)

        self.assertEqual(decimal.Decimal('2.00'),
                         result['cpu']['cumulated'])
        self.assertEqual([1.25, 0, 0.75],
                         list(result['cpu']['hourly'].values()))
        self.assertEqual([2.0, 0, 0],
                         list(result['volume']['hourly'].values()))

    def test_build_raw_usage_data_v1(self):
        data = {
            'dataframes': [
                {
                    'begin': '2026-07-16T10:00:00',
                    'end': '2026-07-16T11:00:00',
                    'resources': [{
                        'service': 'instance',
                        'desc': {
                            'id': 'instance-1',
                            'project_id': 'project-1',
                            'flavor': 'm1.small',
                            'vcpus': 2,
                        },
                        'volume': '1E+1',
                        'rating': '0',
                    }],
                },
            ],
        }

        result = raw_usage._build_raw_usage_data_v1(
            data, {'instance': 'instance'})

        self.assertEqual([{
            'begin': '2026-07-16T10:00:00',
            'end': '2026-07-16T11:00:00',
            'metric': 'instance',
            'resource_id': 'instance-1',
            'quantity': '10',
            'unit': 'instance',
            'details': 'flavor=m1.small, vcpus=2',
        }], result)

    def test_raw_usage_sort_accepts_mixed_key_types(self):
        rows = [
            {'begin': None, 'metric': 7, 'resource_id': '-'},
            {'begin': None, 'metric': 'instance', 'resource_id': 42},
        ]

        result = sorted(
            rows, key=raw_usage._raw_usage_sort_key, reverse=True)

        self.assertEqual('instance', result[0]['metric'])

    def test_build_raw_usage_data_v2_ignores_zero_rating(self):
        data = {
            'dataframes': [{
                'period': {
                    'begin': '2026-07-16T10:00:00',
                    'end': '2026-07-16T11:00:00',
                },
                'usage': {
                    'instance': [{
                        'vol': {'qty': '2E+1', 'unit': 'instance'},
                        'rating': {'price': '0'},
                        'groupby': {
                            'id': 'instance-1',
                            'project_id': 'project-1',
                        },
                        'metadata': {
                            'flavor': 'm1.small',
                            'vcpus': 2,
                        },
                    }],
                },
            }],
        }

        result = raw_usage._build_raw_usage_data_v2(data)

        self.assertEqual([{
            'begin': '2026-07-16T10:00:00',
            'end': '2026-07-16T11:00:00',
            'metric': 'instance',
            'resource_id': 'instance-1',
            'quantity': '20',
            'unit': 'instance',
            'details': 'flavor=m1.small, vcpus=2',
        }], result)

    def test_reporting_does_not_include_raw_usage(self):
        self.assertEqual(
            (reporting.CostRepartitionTab,),
            reporting.ReportingTabs.tabs,
        )

    @mock.patch.object(raw_usage.api, 'cloudkittyclient')
    def test_raw_usage_page_does_not_query_storage_without_filter(
            self, client_factory):
        client = client_factory.return_value
        client.info.get_metric.return_value = {
            'metrics': [{'metric_id': 'instance', 'unit': 'instance'}]
        }
        request = SimpleNamespace(
            GET={},
            user=SimpleNamespace(tenant_id='project-1'),
        )
        view = raw_usage.IndexView()
        view.request = request

        context = view.get_context_data()

        client.storage.get_dataframes.assert_not_called()
        self.assertFalse(context['queried'])
        self.assertEqual([], context['usage_rows'])

    @mock.patch.object(raw_usage.api, 'cloudkittyclient')
    def test_raw_usage_page_filters_v1_storage(self, client_factory):
        client = client_factory.return_value
        client.storage.get_dataframes.return_value = {'dataframes': []}
        client.info.get_metric.return_value = {
            'metrics': [
                {'metric_id': 'instance', 'unit': 'instance'},
                {'unit': 'undefined'},
            ]
        }
        request = SimpleNamespace(
            GET={
                'start': '2026-07-01',
                'end': '2026-07-16',
                'resource_type': 'instance',
            },
            user=SimpleNamespace(tenant_id='project-1'),
        )
        view = raw_usage.IndexView()
        view.request = request

        settings = SimpleNamespace(OPENSTACK_CLOUDKITTY_STORAGE_VERSION=1)
        with mock.patch.object(raw_usage, 'settings', settings):
            context = view.get_context_data()

        client_factory.assert_called_once_with(request)
        client.storage.get_dataframes.assert_called_once_with(
            begin='2026-07-01T00:00:00',
            end='2026-07-16T23:59:59',
            tenant_id='project-1',
            resource_type='instance',
        )
        client.info.get_metric.assert_called_once_with()
        self.assertTrue(context['queried'])
        self.assertEqual([], context['usage_rows'])

    def test_v2_raw_usage_follows_pagination(self):
        client = mock.Mock()
        dataframe = {'period': {}, 'usage': {}}
        client.dataframes.get_dataframes.side_effect = [
            {'total': 101, 'dataframes': [dataframe] * 100},
            {'total': 101, 'dataframes': [dataframe]},
        ]

        result = raw_usage._get_raw_usage_data_v2(
            client, 'project-1', 'instance', 'begin', 'end')

        self.assertEqual(101, len(result['dataframes']))
        self.assertEqual([
            mock.call(
                begin='begin', end='end',
                filters={
                    'project_id': 'project-1',
                    'type': 'instance',
                }, offset=0, limit=100),
            mock.call(
                begin='begin', end='end',
                filters={
                    'project_id': 'project-1',
                    'type': 'instance',
                }, offset=100, limit=100),
        ], client.dataframes.get_dataframes.call_args_list)

    def test_v2_raw_usage_follows_full_pages_without_total(self):
        client = mock.Mock()
        dataframe = {'period': {}, 'usage': {}}
        client.dataframes.get_dataframes.side_effect = [
            {'dataframes': [dataframe] * 100},
            {'dataframes': [dataframe]},
        ]

        result = raw_usage._get_raw_usage_data_v2(
            client, 'project-1', 'instance', 'begin', 'end')

        self.assertEqual(101, len(result['dataframes']))
        self.assertEqual(2, client.dataframes.get_dataframes.call_count)

    def test_v2_raw_usage_treats_not_found_as_empty(self):
        client = mock.Mock()
        client.dataframes.get_dataframes.side_effect = \
            raw_usage.http_exceptions.HttpError(http_status=404)

        result = raw_usage._get_raw_usage_data_v2(
            client, 'project-1', 'instance', 'begin', 'end')

        self.assertEqual({'dataframes': []}, result)

    @mock.patch.object(raw_usage.api, 'cloudkittyclient')
    @mock.patch.object(raw_usage, '_get_raw_usage_data_v2')
    def test_raw_usage_page_filters_v2_storage(self, get_data, client_factory):
        get_data.return_value = {'dataframes': []}
        info_client = mock.Mock()
        info_client.info.get_metric.return_value = {
            'metrics': [{'metric_id': 'instance', 'unit': 'instance'}]
        }
        v2_client = mock.Mock()
        client_factory.side_effect = [info_client, v2_client]
        request = SimpleNamespace(
            GET={
                'start': '2026-07-01',
                'end': '2026-07-16',
                'resource_type': 'instance',
            },
            user=SimpleNamespace(tenant_id='project-1'),
        )
        view = raw_usage.IndexView()
        view.request = request
        settings = SimpleNamespace(OPENSTACK_CLOUDKITTY_STORAGE_VERSION=2)

        with mock.patch.object(raw_usage, 'settings', settings):
            context = view.get_context_data()

        self.assertEqual([
            mock.call(request),
            mock.call(request, version='2'),
        ], client_factory.call_args_list)
        get_data.assert_called_once_with(
            v2_client,
            'project-1',
            'instance',
            '2026-07-01T00:00:00',
            '2026-07-16T23:59:59',
        )
        self.assertTrue(context['queried'])
        self.assertEqual([], context['usage_rows'])
