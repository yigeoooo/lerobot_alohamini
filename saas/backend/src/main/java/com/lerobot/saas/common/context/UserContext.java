package com.lerobot.saas.common.context;

import lombok.AllArgsConstructor;
import lombok.Data;

@Data
@AllArgsConstructor
public class UserContext {
    private String userId;
    private String organizationId;
    private Boolean systemAdmin;
}
