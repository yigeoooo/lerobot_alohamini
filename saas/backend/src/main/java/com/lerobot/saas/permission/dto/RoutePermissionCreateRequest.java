package com.lerobot.saas.permission.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class RoutePermissionCreateRequest {

    @NotBlank(message = "路由名称不能为空")
    private String routeName;

    @NotBlank(message = "路由路径不能为空")
    private String routePath;

    @NotBlank(message = "组件路径不能为空")
    private String componentPath;

    @NotBlank(message = "页面标题不能为空")
    private String title;

    private String icon;

    private Integer sort;

    private Boolean adminOnly;
}
