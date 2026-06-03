package com.lerobot.saas.user.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class UserCreateRequest {

    @NotBlank(message = "姓名不能为空")
    private String name;

    private Integer gender;

    @NotBlank(message = "组织不能为空")
    private String organizationId;

    @Email(message = "邮箱格式不正确")
    @NotBlank(message = "邮箱不能为空")
    private String email;

    private String rawPassword;

    private String avatarIconId;

    private Boolean systemAdmin;
}
