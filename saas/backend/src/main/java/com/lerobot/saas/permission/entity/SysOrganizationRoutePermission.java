package com.lerobot.saas.permission.entity;

import com.baomidou.mybatisplus.annotation.TableName;
import com.lerobot.saas.common.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
@TableName("sys_organization_route_permission")
public class SysOrganizationRoutePermission extends BaseEntity {
    private String organizationId;
    private String routePermissionId;
}
