package com.lerobot.saas.dataset.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import java.math.BigDecimal;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_dataset")
public class SysDataset extends BaseEntity {
    private String datasetName;
    private String organizationId;
    private String userId;
    private String originalFileName;
    private String storagePath;
    private String uploadStatus;
    private String errorMessage;
    private String codebaseVersion;
    private String robotType;
    private Integer totalEpisodes;
    private Long totalFrames;
    private Integer totalTasks;
    private Integer fps;
    private BigDecimal dataFilesSizeMb;
    private BigDecimal videoFilesSizeMb;
    private Integer featureCount;
    private Integer cameraCount;
    private String featureKeys;
    private String cameraKeys;
    private String metadataJson;
}
