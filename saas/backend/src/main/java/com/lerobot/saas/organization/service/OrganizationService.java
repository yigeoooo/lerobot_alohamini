package com.lerobot.saas.organization.service;

import com.lerobot.saas.organization.dto.OrganizationCreateRequest;
import com.lerobot.saas.organization.dto.OrganizationUpdateRequest;
import com.lerobot.saas.organization.entity.SysOrganization;
import java.util.List;

public interface OrganizationService {

    List<SysOrganization> listOrganizations(String keyword);

    void createOrganization(OrganizationCreateRequest request);

    void updateOrganization(String organizationId, OrganizationUpdateRequest request);

    void deleteOrganization(String organizationId);
}
