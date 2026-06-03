package com.lerobot.saas.user.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class UserResetPasswordRequest {

    @NotBlank(message = "新密码不能为空")
    private String newPassword;
}
