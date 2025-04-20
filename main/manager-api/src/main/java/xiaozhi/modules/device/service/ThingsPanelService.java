package xiaozhi.modules.device.service;

import xiaozhi.modules.device.entity.DeviceEntity;

public interface ThingsPanelService {
    /**
     * 注册设备到 ThingsPanel
     * @param deviceDTO 设备信息
     * @return 注册结果
     */
    String registerDevice(DeviceEntity deviceInfo);
} 