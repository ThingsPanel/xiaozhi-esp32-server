package xiaozhi.modules.device.service.impl;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import lombok.extern.slf4j.Slf4j;
import xiaozhi.modules.device.dto.ThingsPanelDeviceDTO;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.ThingsPanelService;
import xiaozhi.modules.sys.service.SysParamsService;

@Slf4j
@Service
public class ThingsPanelServiceImpl implements ThingsPanelService {

    @Autowired
    private SysParamsService sysParamsService;
    
    private final RestTemplate restTemplate = new RestTemplate();
    
    @Override
    public String registerDevice(DeviceEntity deviceInfo) {
        try {
            // 获取配置参数
            String baseUrl = sysParamsService.getValue("thingspanel.base_url", true);
            String apiKey = sysParamsService.getValue("thingspanel.api_key", true);
            String deviceConfigId = sysParamsService.getValue("thingspanel.device_config_id", true);

            log.info("ThingsPanel配置: baseUrl={}, apiKey={}, deviceConfigId={}", baseUrl, apiKey, deviceConfigId);
            System.out.println("ThingsPanel配置: baseUrl=" + baseUrl + ", apiKey=" + apiKey + ", deviceConfigId=" + deviceConfigId);

            // 自动注册设备到ThingsPanel
            ThingsPanelDeviceDTO deviceDTO = new ThingsPanelDeviceDTO();
            // 设置设备信息
            deviceDTO.setName(deviceInfo.getBoard());
            deviceDTO.setDevice_number(deviceInfo.getId());
            deviceDTO.setDevice_config_id(deviceConfigId);
            deviceDTO.setAdditional_info("{\"macAddress\":\"" + deviceInfo.getMacAddress() + "\"}");
            
            // 设置请求头
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("x-api-key", apiKey);
            
            // 创建请求实体
            HttpEntity<ThingsPanelDeviceDTO> request = new HttpEntity<>(deviceDTO, headers);
            
            // 发送请求到 ThingsPanel
            String url = baseUrl + "/device";
            log.info("发送请求到ThingsPanel: url={}, body={}", url, deviceDTO);
            System.out.println("发送请求到ThingsPanel: url=" + url + ", body=" + deviceDTO);
            
            return restTemplate.postForObject(url, request, String.class);
        } catch (Exception e) {
            log.error("注册设备到ThingsPanel失败: {}", e.getMessage(), e);
            System.out.println("注册设备到ThingsPanel失败: " + e.getMessage());
            e.printStackTrace();
            throw e;
        }
    }
} 