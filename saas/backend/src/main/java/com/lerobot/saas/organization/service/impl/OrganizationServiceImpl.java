package com.lerobot.saas.organization.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.organization.dao.OrganizationDao;
import com.lerobot.saas.organization.dto.OrganizationCreateRequest;
import com.lerobot.saas.organization.dto.OrganizationUpdateRequest;
import com.lerobot.saas.organization.entity.SysOrganization;
import com.lerobot.saas.organization.service.OrganizationService;
import com.lerobot.saas.permission.dao.OrganizationRoutePermissionDao;
import com.lerobot.saas.permission.dao.RoutePermissionDao;
import com.lerobot.saas.permission.entity.SysOrganizationRoutePermission;
import com.lerobot.saas.permission.entity.SysRoutePermission;
import com.lerobot.saas.user.dao.UserDao;
import com.lerobot.saas.user.entity.SysUser;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class OrganizationServiceImpl implements OrganizationService {

    private final OrganizationDao organizationDao;
    private final UserDao userDao;
    private final RoutePermissionDao routePermissionDao;
    private final OrganizationRoutePermissionDao organizationRoutePermissionDao;

    public OrganizationServiceImpl(OrganizationDao organizationDao,
                                   UserDao userDao,
                                   RoutePermissionDao routePermissionDao,
                                   OrganizationRoutePermissionDao organizationRoutePermissionDao) {
        this.organizationDao = organizationDao;
        this.userDao = userDao;
        this.routePermissionDao = routePermissionDao;
        this.organizationRoutePermissionDao = organizationRoutePermissionDao;
    }

    @Override
    public List<SysOrganization> listOrganizations(String keyword) {
        return organizationDao.selectOrganizations(keyword);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createOrganization(OrganizationCreateRequest request) {
        checkDuplicate(null, request.getOrganizationName(), request.getOrganizationCode());
        SysOrganization organization = new SysOrganization();
        organization.setOrganizationName(request.getOrganizationName());
        organization.setOrganizationCode(StringUtils.hasText(request.getOrganizationCode()) ? request.getOrganizationCode() : null);
        organization.setDescription(request.getDescription());
        organizationDao.insert(organization);
        assignBaseRoutes(organization.getId());
    }

    @Override
    public void updateOrganization(String organizationId, OrganizationUpdateRequest request) {
        SysOrganization organization = organizationDao.selectById(organizationId);
        if (organization == null) {
            throw new BusinessException("组织不存在");
        }
        checkDuplicate(organizationId, request.getOrganizationName(), request.getOrganizationCode());
        organization.setOrganizationName(request.getOrganizationName());
        organization.setOrganizationCode(StringUtils.hasText(request.getOrganizationCode()) ? request.getOrganizationCode() : null);
        organization.setDescription(request.getDescription());
        organizationDao.updateById(organization);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteOrganization(String organizationId) {
        SysOrganization organization = organizationDao.selectById(organizationId);
        if (organization == null) {
            throw new BusinessException("组织不存在");
        }
        organizationDao.deleteById(organizationId);
        userDao.delete(new LambdaQueryWrapper<SysUser>().eq(SysUser::getOrganizationId, organizationId));
        organizationRoutePermissionDao.update(null, new LambdaUpdateWrapper<SysOrganizationRoutePermission>()
                .eq(SysOrganizationRoutePermission::getOrganizationId, organizationId)
                .set(SysOrganizationRoutePermission::getDeleted, 1));
    }

    private void checkDuplicate(String organizationId, String organizationName, String organizationCode) {
        Long nameCount = organizationDao.selectCount(new LambdaQueryWrapper<SysOrganization>()
                .eq(SysOrganization::getOrganizationName, organizationName)
                .ne(StringUtils.hasText(organizationId), SysOrganization::getId, organizationId));
        if (nameCount != null && nameCount > 0) {
            throw new BusinessException("组织名称已存在");
        }
        if (StringUtils.hasText(organizationCode)) {
            Long codeCount = organizationDao.selectCount(new LambdaQueryWrapper<SysOrganization>()
                    .eq(SysOrganization::getOrganizationCode, organizationCode)
                    .ne(StringUtils.hasText(organizationId), SysOrganization::getId, organizationId));
            if (codeCount != null && codeCount > 0) {
                throw new BusinessException("组织编码已存在");
            }
        }
    }

    private void assignBaseRoutes(String organizationId) {
        List<SysRoutePermission> baseRoutes = routePermissionDao.selectList(new LambdaQueryWrapper<SysRoutePermission>()
                .in(SysRoutePermission::getRoutePath, List.of("/", "/profile")));
        for (SysRoutePermission baseRoute : baseRoutes) {
            SysOrganizationRoutePermission relation = new SysOrganizationRoutePermission();
            relation.setOrganizationId(organizationId);
            relation.setRoutePermissionId(baseRoute.getId());
            organizationRoutePermissionDao.insert(relation);
        }
    }
}
