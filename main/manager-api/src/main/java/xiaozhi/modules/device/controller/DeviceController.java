package xiaozhi.modules.device.controller;

import java.util.List;
import java.util.Map;
import java.util.HashMap;

import org.apache.commons.lang3.StringUtils;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.redis.RedisKeys;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.common.user.UserDetail;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.device.dto.DeviceRegisterDTO;
import xiaozhi.modules.device.dto.DeviceUnBindDTO;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.device.service.ThingsPanelService;
import xiaozhi.modules.sys.service.SysParamsService;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;

@Slf4j
@Tag(name = "设备管理")
@AllArgsConstructor
@RestController
@RequestMapping("/device")
public class DeviceController {
    private final DeviceService deviceService;

    private final RedisUtils redisUtils;
    private final ThingsPanelService thingsPanelService;
    private final SysParamsService sysParamsService;

    @PostMapping("/bind/{agentId}/{deviceCode}")
    @Operation(summary = "绑定设备")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> bindDevice(@PathVariable String agentId, @PathVariable String deviceCode) {
        DeviceEntity deviceInfo = deviceService.deviceActivation(agentId, deviceCode);
        thingsPanelService.registerDevice(deviceInfo);
        return new Result<>();
    }

    @PostMapping("/bind")
    @Operation(summary = "系统级绑定设备")
    public Result<Map<String, String>> bindDeviceInternal(@RequestBody Map<String, Object> request) {
        try {
            String secret = (String) request.get("secret");
            String agentId = (String) request.get("agent_id");
            String deviceCode = (String) request.get("device_code");
            String externalApiKey = (String) request.get("external_api_key");
            
            if (StringUtils.isBlank(agentId) || StringUtils.isBlank(deviceCode)) {
                return new Result<Map<String, String>>().error(ErrorCode.NOT_NULL, "参数不能为空");
            }

            if (StringUtils.isBlank(secret)) {
                return new Result<Map<String, String>>().error(ErrorCode.NOT_NULL, "secret 参数不能为空");
            }

            // 权限检查
            checkSecret(secret);

            DeviceEntity deviceInfo = deviceService.deviceActivation(agentId, deviceCode);
            thingsPanelService.registerDevice(deviceInfo);

            // 返回设备信息
            Map<String, String> deviceData = new HashMap<>();
            deviceData.put("device_name", deviceInfo.getBoard());
            deviceData.put("device_number", deviceInfo.getId());
            deviceData.put("device_description", deviceInfo.getAlias());

            return new Result<Map<String, String>>().ok(deviceData);
        } catch (Exception e) {
            log.error("绑定设备失败", e);
            return new Result<Map<String, String>>().error(ErrorCode.NOT_NULL, "绑定设备失败" + e.getMessage());
        }
    }

    @PostMapping("/register")
    @Operation(summary = "注册设备")
    public Result<String> registerDevice(@RequestBody DeviceRegisterDTO deviceRegisterDTO) {
        String macAddress = deviceRegisterDTO.getMacAddress();
        if (StringUtils.isBlank(macAddress)) {
            return new Result<String>().error(ErrorCode.NOT_NULL, "mac地址不能为空");
        }
        // 生成六位验证码
        String code = String.valueOf(Math.random()).substring(2, 8);
        String key = RedisKeys.getDeviceCaptchaKey(code);
        String existsMac = null;
        do {
            existsMac = (String) redisUtils.get(key);
        } while (StringUtils.isNotBlank(existsMac));

        redisUtils.set(key, macAddress);
        return new Result<String>().ok(code);
    }

    @GetMapping("/bind/{agentId}")
    @Operation(summary = "获取已绑定设备")
    @RequiresPermissions("sys:role:normal")
    public Result<List<DeviceEntity>> getUserDevices(@PathVariable String agentId) {
        UserDetail user = SecurityUser.getUser();
        List<DeviceEntity> devices = deviceService.getUserDevices(user.getId(), agentId);
        return new Result<List<DeviceEntity>>().ok(devices);
    }

    @PostMapping("/unbind")
    @Operation(summary = "解绑设备")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> unbindDevice(@RequestBody DeviceUnBindDTO unDeviveBind) {
        UserDetail user = SecurityUser.getUser();
        deviceService.unbindDevice(user.getId(), unDeviveBind.getDeviceId());
        return new Result<Void>();
    }

    @PutMapping("/enableOta/{id}/{status}")
    @Operation(summary = "启用/关闭OTA自动升级")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> enableOtaUpgrade(@PathVariable String id, @PathVariable Integer status) {
        DeviceEntity entity = deviceService.selectById(id);
        if (entity == null) {
            return new Result<Void>().error("设备不存在");
        }
        entity.setAutoUpdate(status);
        deviceService.updateById(entity);
        return new Result<Void>();
    }

    @PostMapping("/status")
    @Operation(summary = "更新设备状态")
    public Result<Void> updateDeviceStatus(@RequestBody Map<String, Object> request) {
        try {
            String deviceId = (String) request.get("device_id");
            Integer status = (Integer) request.get("status");
            String secret = (String) request.get("secret");
            
            if (StringUtils.isBlank(deviceId) || status == null) {
                return new Result<Void>().error(ErrorCode.NOT_NULL, "设备ID和状态不能为空");
            }

            if (StringUtils.isBlank(secret)) {
                return new Result<Void>().error(ErrorCode.NOT_NULL, "secret不能为空");
            }

            checkSecret(secret);

            log.info("更新设备状态: deviceId={}, status={}", deviceId, status);
            
            // 更新设备状态
            deviceService.updateDeviceStatus(deviceId, status);
            
            // 同步更新ThingsPanel状态
            thingsPanelService.updateDeviceStatus(deviceId, status);
            
            return new Result<Void>();
        } catch (Exception e) {
            log.error("更新设备状态失败", e);
            return new Result<Void>().error(ErrorCode.NOT_NULL, "更新设备状态失败: " + e.getMessage());
        }
    }

    private void checkSecret(String secret) {
        String secretParam = sysParamsService.getValue(Constant.SERVER_SECRET, true);
        // 验证密钥
        if (StringUtils.isBlank(secret) || !secret.equals(secretParam)) {
            throw new RenException("密钥错误");
        }
    }
}