package com.lerobot.saas.permission.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.organization.dao.OrganizationDao;
import com.lerobot.saas.organization.entity.SysOrganization;
import com.lerobot.saas.permission.dao.OrganizationRoutePermissionDao;
import com.lerobot.saas.permission.dao.RoutePermissionDao;
import com.lerobot.saas.permission.dto.RoutePermissionCreateRequest;
import com.lerobot.saas.permission.entity.SysOrganizationRoutePermission;
import com.lerobot.saas.permission.entity.SysRoutePermission;
import com.lerobot.saas.permission.service.RoutePermissionService;
import java.util.Collections;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RoutePermissionServiceImpl implements RoutePermissionService {

    private final RoutePermissionDao routePermissionDao;
    private final OrganizationRoutePermissionDao organizationRoutePermissionDao;
    private final OrganizationDao organizationDao;

    public RoutePermissionServiceImpl(RoutePermissionDao routePermissionDao,
                                      OrganizationRoutePermissionDao organizationRoutePermissionDao,
                                      OrganizationDao organizationDao) {
        this.routePermissionDao = routePermissionDao;
        this.organizationRoutePermissionDao = organizationRoutePermissionDao;
        this.organizationDao = organizationDao;
    }

    @Override
    public List<SysRoutePermission> listRoutePermissions() {
        return routePermissionDao.selectAllActiveRoutePermissions();
    }

    @Override
    public void createRoutePermission(RoutePermissionCreateRequest request) {
        Long count = routePermissionDao.selectCount(new LambdaQueryWrapper<SysRoutePermission>()
                .eq(SysRoutePermission::getRoutePath, request.getRoutePath()));
        if (count != null && count > 0) {
            throw new BusinessException("路由路径已存在");
        }
        SysRoutePermission permission = new SysRoutePermission();
        permission.setRouteName(request.getRouteName());
        permission.setRoutePath(request.getRoutePath());
        permission.setComponentPath(request.getComponentPath());
        permission.setTitle(request.getTitle());
        permission.setIcon(request.getIcon());
        permission.setSort(request.getSort());
        permission.setAdminOnly(Boolean.TRUE.equals(request.getAdminOnly()));
        routePermissionDao.insert(permission);
    }

    @Override
    public List<String> getOrganizationRouteIds(String organizationId) {
        return organizationRoutePermissionDao.selectRouteIdsByOrganizationId(organizationId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void assignRoutesToOrganization(String organizationId, List<String> routePermissionIds) {
        SysOrganization organization = organizationDao.selectById(organizationId);
        if (organization == null) {
            throw new BusinessException("组织不存在");
        }
        organizationRoutePermissionDao.deleteByOrganizationIdPhysical(organizationId);
        List<String> safeRouteIds = routePermissionIds == null ? Collections.emptyList() : routePermissionIds;
        for (String routePermissionId : safeRouteIds) {
            SysOrganizationRoutePermission relation = new SysOrganizationRoutePermission();
            relation.setOrganizationId(organizationId);
            relation.setRoutePermissionId(routePermissionId);
            organizationRoutePermissionDao.insert(relation);
        }
    }
}
