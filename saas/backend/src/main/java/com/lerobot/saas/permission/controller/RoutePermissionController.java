package com.lerobot.saas.permission.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.permission.dto.OrganizationRouteAssignRequest;
import com.lerobot.saas.permission.dto.RoutePermissionCreateRequest;
import com.lerobot.saas.permission.entity.SysRoutePermission;
import com.lerobot.saas.permission.service.RoutePermissionService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/route-permissions")
public class RoutePermissionController {

    private final RoutePermissionService routePermissionService;

    public RoutePermissionController(RoutePermissionService routePermissionService) {
        this.routePermissionService = routePermissionService;
    }

    @GetMapping
    public ApiResponse<List<SysRoutePermission>> list() {
        return ApiResponse.success(routePermissionService.listRoutePermissions());
    }

    @PostMapping
    public ApiResponse<Void> create(@Valid @RequestBody RoutePermissionCreateRequest request) {
        routePermissionService.createRoutePermission(request);
        return ApiResponse.success("创建成功", null);
    }

    @GetMapping("/organizations/{organizationId}")
    public ApiResponse<List<String>> getOrganizationRouteIds(@PathVariable String organizationId) {
        return ApiResponse.success(routePermissionService.getOrganizationRouteIds(organizationId));
    }

    @PostMapping("/organizations/{organizationId}")
    public ApiResponse<Void> assignOrganizationRoutes(@PathVariable String organizationId,
                                                      @Valid @RequestBody OrganizationRouteAssignRequest request) {
        routePermissionService.assignRoutesToOrganization(organizationId, request.getRoutePermissionIds());
        return ApiResponse.success("分配成功", null);
    }
}
