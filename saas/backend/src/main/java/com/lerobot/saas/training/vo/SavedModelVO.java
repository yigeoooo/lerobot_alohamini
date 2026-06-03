package com.lerobot.saas.training.vo;

import java.time.LocalDateTime;

public record SavedModelVO(
        String name,
        String path,
        Long sizeBytes,
        LocalDateTime updatedTime
) {
}
