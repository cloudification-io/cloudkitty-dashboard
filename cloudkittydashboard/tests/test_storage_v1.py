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

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'openstack_dashboard.settings')
django.setup()

summary = importlib.import_module(
    'cloudkittydashboard.dashboards.admin.summary.views')
reporting = importlib.import_module(
    'cloudkittydashboard.dashboards.project.reporting.views')


class SummaryStorageVersionTests(unittest.TestCase):

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
