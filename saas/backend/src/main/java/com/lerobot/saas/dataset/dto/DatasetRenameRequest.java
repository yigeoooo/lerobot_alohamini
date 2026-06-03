package com.lerobot.saas.dataset.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class DatasetRenameRequest {

    @NotBlank(message = "数据集名称不能为空")
    private String datasetName;
}
