package com.lerobot.saas.auth.vo;

public record LoginUserVO(
        String id,
        String name,
        Integer gender,
        String email,
        String organizationId,
        String organizationName,
        String avatarIconId,
        String avatarIconName,
        Boolean systemAdmin
) {
}
