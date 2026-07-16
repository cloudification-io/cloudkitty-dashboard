# Copyright 2018 Objectif Libre
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from horizon import tables

from openstack_dashboard.api import keystone as api_keystone

from cloudkittydashboard.api import cloudkitty as api
from cloudkittydashboard.dashboards.admin.summary import tables as sum_tables
from cloudkittydashboard import utils

from cloudkittydashboard import forms

rate_prefix = getattr(settings,
                      'OPENSTACK_CLOUDKITTY_RATE_PREFIX', None)
rate_postfix = getattr(settings,
                       'OPENSTACK_CLOUDKITTY_RATE_POSTFIX', None)


def _uses_v1_storage():
    return int(getattr(
        settings, 'OPENSTACK_CLOUDKITTY_STORAGE_VERSION', 2)) == 1


class IndexView(tables.DataTableView):
    template_name = 'admin/rating_summary/index.html'
    table_class = sum_tables.SummaryTable

    def get_data(self):
        if _uses_v1_storage():
            data = api.cloudkittyclient(
                self.request).report.get_summary(
                    groupby=['tenant_id'], all_tenants=True)['summary']
            project_key = 'tenant_id'
        else:
            summary = api.cloudkittyclient(
                self.request, version='2').summary.get_summary(
                groupby=['project_id'], response_format='object')
            data = summary.get('results')
            project_key = 'project_id'

        tenants, unused = api_keystone.tenant_list(self.request)
        tenants = {tenant.id: tenant.name for tenant in tenants}

        total = sum([float(r.get('rate')) for r in data])
        data.append({
            project_key: 'ALL',
            'rate': total,
        })

        data = api.identify(data, key=project_key)
        for tenant in data:
            tenant['tenant_id'] = tenant.get(project_key)
            tenant['name'] = tenants.get(tenant.id, '-')
            tenant['rate'] = utils.formatRate(float(tenant['rate']),
                                              rate_prefix, rate_postfix)
        data[-1]['name'] = _('Cloud Total')
        return data


class TenantDetailsView(tables.DataTableView):
    template_name = 'admin/rating_summary/details.html'
    table_class = sum_tables.TenantSummaryTable

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['groupby_list'] = getattr(settings,
                                          'OPENSTACK_CLOUDKITTY_GROUPBY_LIST',
                                          ['type'])
        return context

    def get_data(self):
        tenant_id = self.kwargs['project_id']
        form = forms.CheckBoxForm(self.request.GET)
        groupby = form.get_selected_fields()

        if _uses_v1_storage():
            client = api.cloudkittyclient(self.request)
            kwargs = {'groupby': ['res_type']}
            if tenant_id == 'ALL':
                kwargs['all_tenants'] = True
            else:
                kwargs['tenant_id'] = tenant_id
            data = client.report.get_summary(**kwargs)['summary']
            for item in data:
                item['type'] = item.pop('res_type')
        elif tenant_id == 'ALL':
            summary = api.cloudkittyclient(
                self.request, version='2'
            ).summary.get_summary(groupby=groupby, response_format='object')
        else:
            summary = api.cloudkittyclient(
                self.request, version='2'
            ).summary.get_summary(
                filters={'project_id': tenant_id},
                groupby=groupby,
                response_format='object',
            )

        if not _uses_v1_storage():
            data = summary.get('results')
        total = sum([float(r.get('rate')) for r in data])

        if not groupby:
            data = [{'type': 'TOTAL', 'rate': total}]

        else:
            data.append({'type': 'TOTAL', 'rate': total})
            for item in data:
                item['rate'] = utils.formatRate(
                    float(item['rate']), rate_prefix, rate_postfix)

        return data
