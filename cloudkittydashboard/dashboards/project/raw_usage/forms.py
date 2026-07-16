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

from django import forms
from django.utils.translation import gettext_lazy as _

from cloudkittydashboard.forms import base


class RawUsageFilterForm(base.DateForm):
    resource_type = forms.ChoiceField(
        label=_("Resource type"),
        choices=(),
    )

    def __init__(self, *args, resource_types=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', _("Select a resource type"))]
        choices.extend((value, value) for value in resource_types)
        self.fields['resource_type'].choices = choices
        self.fields['resource_type'].widget.attrs['class'] = 'form-control'

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start')
        end = cleaned_data.get('end')
        if start and end and end < start:
            self.add_error(
                'end',
                _("The end date must not be earlier than the start date."),
            )
        return cleaned_data
