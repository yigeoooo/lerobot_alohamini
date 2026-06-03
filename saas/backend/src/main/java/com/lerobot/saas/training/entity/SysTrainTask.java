package com.lerobot.saas.training.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_train_task")
public class SysTrainTask extends BaseEntity {
    private String taskName;
    private String organizationId;
    private String userId;
    private String datasetId;
    private String datasetName;
    private String datasetPath;
    private String modelId;
    private String modelCode;
    private String modelName;
    private String outputDir;
    private String policyRepoId;
    private String device;
    private Boolean wandbEnable;
    private Integer steps;
    private Integer batchSize;
    private Boolean useAmp;
    private String optimizerType;
    private String optimizerLr;
    private String optimizerWeightDecay;
    private String optimizerGradClipNorm;
    private Integer logFreq;
    private Integer saveFreq;
    private Integer policyChunkSize;
    private Integer policyActionSteps;
    private String taskStatus;
    private Long processId;
    private String commandText;
    private String logPath;
    private Integer exitCode;
    private String errorMessage;
}
