package com.lerobot.saas.auth.service;

import com.lerobot.saas.auth.dto.LoginRequest;
import com.lerobot.saas.auth.vo.LoginVO;

public interface AuthService {

    LoginVO login(LoginRequest request);

    LoginVO getCurrentProfile();
}
