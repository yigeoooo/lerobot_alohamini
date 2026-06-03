package com.lerobot.saas.auth.controller;

import com.lerobot.saas.auth.dto.LoginRequest;
import com.lerobot.saas.auth.service.AuthService;
import com.lerobot.saas.auth.vo.LoginVO;
import com.lerobot.saas.common.annotation.PublicAccess;
import com.lerobot.saas.common.api.ApiResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PublicAccess
    @PostMapping("/login")
    public ApiResponse<LoginVO> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.success(authService.login(request));
    }

    @GetMapping("/profile")
    public ApiResponse<LoginVO> profile() {
        return ApiResponse.success(authService.getCurrentProfile());
    }
}
