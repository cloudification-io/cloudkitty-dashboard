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

import datetime
import decimal

from django.conf import settings
from django.utils import timezone
from django.views import generic
from keystoneauth1.exceptions import http as http_exceptions

from cloudkittydashboard.api import cloudkitty as api
from cloudkittydashboard.dashboards.project.raw_usage import forms


def _uses_v1_storage():
    return int(getattr(
        settings, 'OPENSTACK_CLOUDKITTY_STORAGE_VERSION', 2)) == 1


def _raw_usage_sort_key(row):
    return tuple(str(row[key] or '') for key in (
        'begin', 'metric', 'resource_id'))


def _format_quantity(quantity):
    if quantity is None:
        return None
    return format(decimal.Decimal(str(quantity)), 'f')


def _build_raw_usage_data_v1(data, units):
    rows = []

    for dataframe in data.get('dataframes', []):
        for resource in dataframe.get('resources', []):
            metric = resource.get('service', '')
            description = resource.get('desc') or {}
            resource_id = next((
                description[key]
                for key in ('resource_id', 'id')
                if description.get(key)
            ), '-')
            details = ', '.join(
                '{}={}'.format(key, value)
                for key, value in sorted(description.items())
                if key not in ('id', 'project_id', 'resource_id')
            )
            rows.append({
                'begin': dataframe.get('begin'),
                'end': dataframe.get('end'),
                'metric': metric,
                'resource_id': resource_id,
                'quantity': _format_quantity(resource.get('volume')),
                'unit': units.get(metric, 'undefined'),
                'details': details,
            })

    return sorted(rows, key=_raw_usage_sort_key, reverse=True)


def _build_raw_usage_data_v2(data):
    rows = []

    for dataframe in data.get('dataframes', []):
        period = dataframe.get('period', {})
        for metric, points in dataframe.get('usage', {}).items():
            for point in points:
                description = dict(point.get('groupby') or {})
                description.update(point.get('metadata') or {})
                resource_id = next((
                    description[key]
                    for key in ('resource_id', 'id')
                    if description.get(key)
                ), '-')
                details = ', '.join(
                    '{}={}'.format(key, value)
                    for key, value in sorted(description.items())
                    if key not in ('id', 'project_id', 'resource_id')
                )
                volume = point.get('vol') or {}
                rows.append({
                    'begin': period.get('begin'),
                    'end': period.get('end'),
                    'metric': metric,
                    'resource_id': resource_id,
                    'quantity': _format_quantity(volume.get('qty')),
                    'unit': volume.get('unit', 'undefined'),
                    'details': details,
                })

    return sorted(rows, key=_raw_usage_sort_key, reverse=True)


def _get_raw_usage_data_v2(client, tenant_id, resource_type, begin, end):
    dataframes = []
    offset = 0
    limit = 100

    while True:
        try:
            response = client.dataframes.get_dataframes(
                begin=begin,
                end=end,
                filters={
                    'project_id': tenant_id,
                    'type': resource_type,
                },
                offset=offset,
                limit=limit,
            )
        except http_exceptions.HttpError as error:
            if error.http_status == 404:
                break
            raise

        page = response.get('dataframes', [])
        dataframes.extend(page)
        offset += len(page)
        total = response.get('total')
        if not page:
            break
        if total is not None and offset >= int(total):
            break
        if total is None and len(page) < limit:
            break

    return {'dataframes': dataframes}


def _get_time_range(form):
    start = form.cleaned_data['start']
    end = form.cleaned_data['end']
    begin = "%4d-%02d-%02dT00:00:00" % (
        start.year, start.month, start.day)
    end = "%4d-%02d-%02dT23:59:59" % (
        end.year, end.month, end.day)
    return begin, end


def _get_initial_dates():
    today = timezone.now().date()
    days_range = getattr(settings, 'OVERVIEW_DAYS_RANGE', None)
    if days_range:
        start = today - datetime.timedelta(days=days_range)
    else:
        start = today.replace(day=1)
    return start, today


class IndexView(generic.TemplateView):
    template_name = 'project/raw_usage/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        info_client = api.cloudkittyclient(self.request)
        metrics = info_client.info.get_metric().get('metrics', [])
        resource_types = sorted({
            metric['metric_id']
            for metric in metrics
            if metric.get('metric_id')
        })
        initial_start, initial_end = _get_initial_dates()
        initial = {
            'start': initial_start.isoformat(),
            'end': initial_end.isoformat(),
        }
        form = forms.RawUsageFilterForm(
            self.request.GET or None,
            initial=initial,
            resource_types=resource_types,
        )
        usage_rows = []
        queried = False

        if form.is_bound and form.is_valid():
            queried = True
            begin, end = _get_time_range(form)
            resource_type = form.cleaned_data['resource_type']
            if _uses_v1_storage():
                data = info_client.storage.get_dataframes(
                    begin=begin,
                    end=end,
                    tenant_id=self.request.user.tenant_id,
                    resource_type=resource_type,
                )
                units = {
                    metric['metric_id']: metric.get('unit', 'undefined')
                    for metric in metrics
                    if metric.get('metric_id')
                }
                usage_rows = _build_raw_usage_data_v1(data, units)
            else:
                client = api.cloudkittyclient(self.request, version='2')
                data = _get_raw_usage_data_v2(
                    client,
                    self.request.user.tenant_id,
                    resource_type,
                    begin,
                    end,
                )
                usage_rows = _build_raw_usage_data_v2(data)

        context.update({
            'form': form,
            'queried': queried,
            'usage_rows': usage_rows,
        })
        return context
