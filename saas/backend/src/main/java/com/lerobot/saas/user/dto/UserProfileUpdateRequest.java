package com.lerobot.saas.user.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class UserProfileUpdateRequest {

    @NotBlank(message = "姓名不能为空")
    private String name;

    private Integer gender;

    @Email(message = "邮箱格式不正确")
    private String email;

    private String avatarIconId;
}
