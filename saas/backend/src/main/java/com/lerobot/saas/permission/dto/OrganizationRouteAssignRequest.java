package com.lerobot.saas.permission.dto;

import jakarta.validation.constraints.NotNull;
import java.util.List;
import lombok.Data;

@Data
public class OrganizationRouteAssignRequest {

    @NotNull(message = "路由权限不能为空")
    private List<String> routePermissionIds;
}
