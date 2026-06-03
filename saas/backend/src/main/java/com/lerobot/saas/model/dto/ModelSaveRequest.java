package com.lerobot.saas.model.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class ModelSaveRequest {

    @NotBlank(message = "模型编码不能为空")
    private String modelCode;

    @NotBlank(message = "模型名称不能为空")
    private String modelName;

    private Integer sort;
}
