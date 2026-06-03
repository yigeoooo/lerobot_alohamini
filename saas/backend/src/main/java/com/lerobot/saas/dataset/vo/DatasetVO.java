package com.lerobot.saas.dataset.vo;

import java.math.BigDecimal;
import java.time.LocalDateTime;

public record DatasetVO(
        String id,
        String datasetName,
        String organizationId,
        String userId,
        String originalFileName,
        String storagePath,
        String uploadStatus,
        String errorMessage,
        String codebaseVersion,
        String robotType,
        Integer totalEpisodes,
        Long totalFrames,
        Integer totalTasks,
        Integer fps,
        BigDecimal dataFilesSizeMb,
        BigDecimal videoFilesSizeMb,
        Integer featureCount,
        Integer cameraCount,
        String featureKeys,
        String cameraKeys,
        String metadataJson,
        LocalDateTime createdTime
) {
}
