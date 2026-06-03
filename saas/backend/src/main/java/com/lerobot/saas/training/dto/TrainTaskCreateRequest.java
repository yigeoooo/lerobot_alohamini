package com.lerobot.saas.training.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class TrainTaskCreateRequest {

    @NotBlank(message = "任务名称不能为空")
    private String taskName;

    @NotBlank(message = "数据集不能为空")
    private String datasetId;

    @NotBlank(message = "模型不能为空")
    private String modelId;

    @NotBlank(message = "模型仓库不能为空")
    private String policyRepoId;

    private String device;
    private Boolean wandbEnable;

    @NotNull(message = "训练步数不能为空")
    private Integer steps;

    @NotNull(message = "batch size 不能为空")
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
}
