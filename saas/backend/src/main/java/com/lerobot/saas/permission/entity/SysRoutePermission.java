package com.lerobot.saas.permission.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_route_permission")
public class SysRoutePermission extends BaseEntity {
    private String routeName;
    private String routePath;
    private String componentPath;
    private String title;
    private String icon;
    private Boolean adminOnly;
}
