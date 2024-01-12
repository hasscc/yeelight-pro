import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_HOST

from . import get_gateway_from_config, init_integration_data
from .core.const import *


def get_flow_schema(defaults: dict):
    return {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, '')): str,
    }


class YeelightProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return OptionsFlowHandler(entry)

    async def async_step_user(self, user_input=None):
        init_integration_data(self.hass)
        errors = {}
        if user_input is None:
            user_input = {}
        if host := user_input.get(CONF_HOST):
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            if gtw := await get_gateway_from_config(self.hass, user_input, renew=True):
                if err := await gtw.check_available():
                    self.context['last_error'] = str(err)
                else:
                    return self.async_create_entry(
                        title=host or DEFAULT_NAME,
                        data=user_input,
                    )
            errors['base'] = 'cannot_access'
        return self.async_show_form(
            step_id='user',
            data_schema=vol.Schema({
                **get_flow_schema(user_input),
                vol.Required(CONF_PID, default=user_input.get(CONF_PID, PID_GATEWAY)): vol.In(GATEWAY_TYPES),
            }),
            errors=errors,
            description_placeholders={'tip': self.context.pop('last_error', '')},
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is None:
            user_input = {}
        if user_input.get(CONF_HOST):
            if gtw := await get_gateway_from_config(self.hass, user_input, renew=True):
                if err := await gtw.check_available():
                    self.context['last_error'] = str(err)
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data={**self.config_entry.data, **user_input}
                    )
                    return self.async_create_entry(title='', data={})
            errors['base'] = 'cannot_access'
        user_input = {
            **self.config_entry.data,
            **self.config_entry.options,
            **user_input,
        }
        return self.async_show_form(
            step_id='init',
            data_schema=vol.Schema(get_flow_schema(user_input)),
            description_placeholders={'tip': self.context.pop('last_error', '')},
        )
