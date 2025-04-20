package xiaozhi.modules.device.dto;

import java.io.Serializable;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "ThingsPanel设备注册信息")
public class ThingsPanelDeviceDTO implements Serializable {
    private static final long serialVersionUID = 1L;

    @Schema(description = "设备编号")
    private String device_number;

    @Schema(description = "设备名称")
    private String name;

    @Schema(description = "产品ID")
    private String product_id;

    @Schema(description = "凭证")
    private String voucher;

    @Schema(description = "协议配置")
    private String protocol_config;

    @Schema(description = "附加信息")
    private String additional_info;

    @Schema(description = "当前版本")
    private String current_version;

    @Schema(description = "设备配置ID")
    private String device_config_id;

    @Schema(description = "标签")
    private String label;

    @Schema(description = "位置")
    private String location;

    @Schema(description = "父设备ID")
    private String parent_id;

    @Schema(description = "备注1")
    private String remark1;

    @Schema(description = "备注2")
    private String remark2;

    @Schema(description = "备注3")
    private String remark3;

    @Schema(description = "子设备地址")
    private String sub_device_addr;

    @Schema(description = "描述")
    private String description;
} 