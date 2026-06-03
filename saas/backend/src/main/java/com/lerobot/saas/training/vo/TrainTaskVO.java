package com.lerobot.saas.training.vo;

import java.time.LocalDateTime;

public record TrainTaskVO(
        String id,
        String taskName,
        String datasetName,
        String datasetPath,
        String modelCode,
        String modelName,
        String outputDir,
        String policyRepoId,
        String device,
        Boolean wandbEnable,
        Integer steps,
        Integer batchSize,
        Boolean useAmp,
        String optimizerType,
        String optimizerLr,
        String optimizerWeightDecay,
        String optimizerGradClipNorm,
        Integer logFreq,
        Integer saveFreq,
        Integer policyChunkSize,
        Integer policyActionSteps,
        String taskStatus,
        Long processId,
        String commandText,
        String logPath,
        Integer exitCode,
        String errorMessage,
        LocalDateTime createdTime,
        LocalDateTime updatedTime
) {
}
