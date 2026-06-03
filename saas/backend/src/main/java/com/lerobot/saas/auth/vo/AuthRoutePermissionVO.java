package com.lerobot.saas.auth.vo;

import lombok.Data;

@Data
public class AuthRoutePermissionVO {
    private String id;
    private String routeName;
    private String routePath;
    private String componentPath;
    private String title;
    private String icon;
    private Integer sort;
    private Boolean adminOnly;
}
