"""Support for cover."""
import logging
from homeassistant.core import callback
from homeassistant.components.cover import (
    CoverEntity,
    DOMAIN as ENTITY_DOMAIN,
    ATTR_POSITION,
    ATTR_CURRENT_POSITION,
)
from homeassistant.helpers.restore_state import RestoreEntity
from . import (
    XDevice,
    XEntity,
    Converter,
    async_add_setuper,
)

_LOGGER = logging.getLogger(__name__)


def setuper(add_entities):
    def setup(device: XDevice, conv: Converter):
        if not (entity := device.entities.get(conv.attr)):
            entity = XCoverEntity(device, conv)
        if not entity.added:
            add_entities([entity])

    return setup


async def async_setup_entry(hass, config_entry, async_add_entities):
    await async_add_setuper(hass, config_entry, ENTITY_DOMAIN, setuper(async_add_entities))


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    await async_add_setuper(hass, config or discovery_info, ENTITY_DOMAIN, setuper(async_add_entities))


class XCoverEntity(XEntity, CoverEntity, RestoreEntity):
    _attr_is_closed = None

    @callback
    def async_set_state(self, data: dict):
        # 处理设备运行状态：根据设备实际返回的 run_state 值映射开合状态
        # （若设备 run_state 为 "opening"/"closing" 可直接匹配，若为其他值需按需调整）
        if 'run_state' in data:
            run_state = data['run_state']
            # 直接通过设备返回的状态字符串判断，无需依赖已移除的 STATE_OPENING/STATE_CLOSING 常量
            self._attr_is_opening = run_state == "opening"  # 匹配设备实际返回的"打开中"状态值
            self._attr_is_closing = run_state == "closing"  # 匹配设备实际返回的"关闭中"状态值
            self._attr_state = run_state  # 保留原始状态值供调试

        # 处理封面位置信息（逻辑不变）
        if ATTR_POSITION in data:
            self._attr_current_cover_position = data[ATTR_POSITION]
            self._attr_is_closed = self._attr_current_cover_position <= 3

    @callback
    def async_restore_last_state(self, state: str, attrs: dict):
        # 恢复历史状态时，同样基于状态字符串判断（逻辑不变，适配新的状态处理方式）
        if state:
            self.async_set_state({'run_state': state})
        if ATTR_CURRENT_POSITION in attrs:
            self.async_set_state({ATTR_POSITION: attrs[ATTR_CURRENT_POSITION]})

    async def async_open_cover(self, **kwargs):
        # 打开封面：设置位置为 100（逻辑不变）
        kwargs[ATTR_POSITION] = 100
        await self.async_set_cover_position(** kwargs)

    async def async_close_cover(self, **kwargs):
        # 关闭封面：设置位置为 0（逻辑不变）
        kwargs[ATTR_POSITION] = 0
        await self.async_set_cover_position(** kwargs)

    async def async_stop_cover(self, **kwargs):
        # 停止封面：发送暂停指令（逻辑不变）
        await self.device_send_props({self._name: 'pause'})

    async def async_set_cover_position(self, **kwargs):
        # 设置封面位置：发送位置参数（逻辑不变）
        await self.device_send_props(kwargs)
