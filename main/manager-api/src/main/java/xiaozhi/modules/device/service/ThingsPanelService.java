package xiaozhi.modules.device.service;

import xiaozhi.modules.device.entity.DeviceEntity;

public interface ThingsPanelService {
    /**
     * 自动注册设备到 ThingsPanel
     * @param deviceDTO 设备信息
     * @return 注册结果
     */
    String registerDevice(DeviceEntity deviceInfo);

    /**
     * 更新设备状态
     * @param deviceId 设备ID
     * @param status 状态
     */
    void updateDeviceStatus(String deviceId, Integer status);

} 