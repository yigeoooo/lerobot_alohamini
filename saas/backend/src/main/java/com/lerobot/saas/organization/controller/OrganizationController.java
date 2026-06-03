package com.lerobot.saas.organization.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.organization.dto.OrganizationCreateRequest;
import com.lerobot.saas.organization.dto.OrganizationUpdateRequest;
import com.lerobot.saas.organization.entity.SysOrganization;
import com.lerobot.saas.organization.service.OrganizationService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/organizations")
public class OrganizationController {

    private final OrganizationService organizationService;

    public OrganizationController(OrganizationService organizationService) {
        this.organizationService = organizationService;
    }

    @GetMapping
    public ApiResponse<List<SysOrganization>> list(@RequestParam(required = false) String keyword) {
        return ApiResponse.success(organizationService.listOrganizations(keyword));
    }

    @PostMapping
    public ApiResponse<Void> create(@Valid @RequestBody OrganizationCreateRequest request) {
        organizationService.createOrganization(request);
        return ApiResponse.success("创建成功", null);
    }

    @PutMapping("/{organizationId}")
    public ApiResponse<Void> update(@PathVariable String organizationId,
                                    @Valid @RequestBody OrganizationUpdateRequest request) {
        organizationService.updateOrganization(organizationId, request);
        return ApiResponse.success("更新成功", null);
    }

    @DeleteMapping("/{organizationId}")
    public ApiResponse<Void> delete(@PathVariable String organizationId) {
        organizationService.deleteOrganization(organizationId);
        return ApiResponse.success("删除成功", null);
    }
}
