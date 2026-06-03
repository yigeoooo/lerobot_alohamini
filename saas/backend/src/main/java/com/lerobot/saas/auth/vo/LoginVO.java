package com.lerobot.saas.auth.vo;

import java.util.List;

public record LoginVO(
        String token,
        LoginUserVO user,
        List<AuthRoutePermissionVO> routePermissions
) {
}
