package com.lerobot.saas.permission.service;

import com.lerobot.saas.permission.dto.RoutePermissionCreateRequest;
import com.lerobot.saas.permission.entity.SysRoutePermission;
import java.util.List;

public interface RoutePermissionService {

    List<SysRoutePermission> listRoutePermissions();

    void createRoutePermission(RoutePermissionCreateRequest request);

    List<String> getOrganizationRouteIds(String organizationId);

    void assignRoutesToOrganization(String organizationId, List<String> routePermissionIds);
}
