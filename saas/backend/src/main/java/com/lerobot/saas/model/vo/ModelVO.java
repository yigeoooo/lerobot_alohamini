package com.lerobot.saas.model.vo;

import java.time.LocalDateTime;
import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class ModelVO {
    private String id;
    private String modelCode;
    private String modelName;
    private Integer sort;
    private LocalDateTime createdTime;
    private LocalDateTime updatedTime;
}
