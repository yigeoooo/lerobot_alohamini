package com.lerobot.saas.icon.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.icon.entity.SysIcon;
import com.lerobot.saas.icon.service.IconService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/icons")
public class IconController {

    private final IconService iconService;

    public IconController(IconService iconService) {
        this.iconService = iconService;
    }

    @GetMapping
    public ApiResponse<List<SysIcon>> list() {
        return ApiResponse.success(iconService.listIcons());
    }
}
