package com.lerobot.saas.system.bootstrap;

import com.lerobot.saas.common.util.PasswordUtils;
import java.util.List;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class SchemaSynchronizer implements ApplicationRunner {

    private static final String DEFAULT_ORGANIZATION_ID = "1910000000000000001";
    private static final String ADMIN_USER_ID = "1910000000000000002";
    private static final String ROUTE_HOME_ID = "1910000000000000011";
    private static final String ROUTE_ORG_ID = "1910000000000000012";
    private static final String ROUTE_PERMISSION_ID = "1910000000000000013";
    private static final String ROUTE_ASSIGN_ID = "1910000000000000014";
    private static final String ROUTE_PROFILE_ID = "1910000000000000015";
    private static final String ROUTE_USER_CENTER_ID = "1910000000000000016";

    private final JdbcTemplate jdbcTemplate;
    private final PasswordUtils passwordUtils;

    public SchemaSynchronizer(JdbcTemplate jdbcTemplate, PasswordUtils passwordUtils) {
        this.jdbcTemplate = jdbcTemplate;
        this.passwordUtils = passwordUtils;
    }

    @Override
    public void run(ApplicationArguments args) {
        createTables();
        syncColumns();
        cleanupTestData();
        initData();
    }

    private void createTables() {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_organization (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    organization_name VARCHAR(100) NOT NULL,
                    organization_code VARCHAR(100) NULL,
                    description VARCHAR(255) NULL,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_icon (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    icon_name VARCHAR(100) NOT NULL,
                    component_name VARCHAR(100) NOT NULL,
                    description VARCHAR(255) NULL,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_user (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    gender TINYINT NOT NULL DEFAULT 1,
                    organization_id VARCHAR(32) NOT NULL,
                    email VARCHAR(100) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    raw_password VARCHAR(100) NOT NULL,
                    avatar_icon_id VARCHAR(32) NULL,
                    system_admin TINYINT NOT NULL DEFAULT 0,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_sys_user_email (email)
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_route_permission (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    route_name VARCHAR(100) NOT NULL,
                    route_path VARCHAR(120) NOT NULL,
                    component_path VARCHAR(150) NOT NULL,
                    title VARCHAR(100) NOT NULL,
                    icon VARCHAR(60) NULL,
                    admin_only TINYINT NOT NULL DEFAULT 0,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_route_permission_path (route_path)
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_organization_route_permission (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    organization_id VARCHAR(32) NOT NULL,
                    route_permission_id VARCHAR(32) NOT NULL,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_org_route_permission (organization_id, route_permission_id)
                )
                """);
    }

    private void syncColumns() {
        ensureBaseColumns("sys_organization");
        ensureBaseColumns("sys_icon");
        ensureBaseColumns("sys_user");
        ensureBaseColumns("sys_route_permission");
        ensureBaseColumns("sys_organization_route_permission");

        ensureColumn("sys_organization", "organization_name", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_organization", "organization_code", "VARCHAR(100) NULL AFTER organization_name");
        ensureColumn("sys_organization", "description", "VARCHAR(255) NULL AFTER organization_code");

        ensureColumn("sys_icon", "icon_name", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_icon", "component_name", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_icon", "description", "VARCHAR(255) NULL AFTER component_name");

        ensureColumn("sys_user", "name", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_user", "gender", "TINYINT NOT NULL DEFAULT 1 AFTER name");
        ensureColumn("sys_user", "organization_id", "VARCHAR(32) NOT NULL AFTER gender");
        ensureColumn("sys_user", "email", "VARCHAR(100) NOT NULL AFTER organization_id");
        ensureColumn("sys_user", "password_hash", "VARCHAR(255) NOT NULL AFTER email");
        ensureColumn("sys_user", "raw_password", "VARCHAR(100) NOT NULL AFTER password_hash");
        ensureColumn("sys_user", "avatar_icon_id", "VARCHAR(32) NULL AFTER raw_password");
        ensureColumn("sys_user", "system_admin", "TINYINT NOT NULL DEFAULT 0 AFTER avatar_icon_id");

        ensureColumn("sys_route_permission", "route_name", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_route_permission", "route_path", "VARCHAR(120) NOT NULL");
        ensureColumn("sys_route_permission", "component_path", "VARCHAR(150) NOT NULL");
        ensureColumn("sys_route_permission", "title", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_route_permission", "icon", "VARCHAR(60) NULL");
        ensureColumn("sys_route_permission", "admin_only", "TINYINT NOT NULL DEFAULT 0 AFTER icon");

        ensureColumn("sys_organization_route_permission", "organization_id", "VARCHAR(32) NOT NULL");
        ensureColumn("sys_organization_route_permission", "route_permission_id", "VARCHAR(32) NOT NULL");
    }

    private void ensureBaseColumns(String tableName) {
        ensureColumn(tableName, "sort", "INT NOT NULL DEFAULT 0");
        ensureColumn(tableName, "deleted", "TINYINT NOT NULL DEFAULT 0");
        ensureColumn(tableName, "created_time", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP");
        ensureColumn(tableName, "updated_time", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP");
    }

    private void ensureColumn(String tableName, String columnName, String definition) {
        Integer count = jdbcTemplate.queryForObject("""
                SELECT COUNT(1)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = ?
                  AND COLUMN_NAME = ?
                """, Integer.class, tableName, columnName);
        if (count == null || count == 0) {
            jdbcTemplate.execute("ALTER TABLE " + tableName + " ADD COLUMN " + columnName + " " + definition);
        }
    }

    private void cleanupTestData() {
        jdbcTemplate.update("DELETE FROM sys_organization_route_permission WHERE route_permission_id IN (SELECT id FROM sys_route_permission WHERE route_path = '/demo-page')");
        jdbcTemplate.update("DELETE FROM sys_route_permission WHERE route_path = '/demo-page'");
    }

    private void initData() {
        initOrganization();
        initIcons();
        initAdminUser();
        initRoutes();
        initDefaultRelations();
    }

    private void initOrganization() {
        jdbcTemplate.update("""
                INSERT INTO sys_organization (id, organization_name, organization_code, description, sort, deleted, created_time, updated_time)
                SELECT ?, 'Aloha', 'ALOHA', '默认组织', 0, 0, NOW(), NOW()
                FROM DUAL
                WHERE NOT EXISTS (SELECT 1 FROM sys_organization WHERE id = ?)
                """, DEFAULT_ORGANIZATION_ID, DEFAULT_ORGANIZATION_ID);
        jdbcTemplate.update("""
                UPDATE sys_organization
                SET organization_name = 'Aloha',
                    organization_code = 'ALOHA',
                    description = '默认组织',
                    updated_time = NOW()
                WHERE id = ?
                """, DEFAULT_ORGANIZATION_ID);
    }

    private void initIcons() {
        List<Object[]> icons = List.of(
                new Object[]{"1910000000000000101", "User", "User", "用户头像", 1},
                new Object[]{"1910000000000000102", "Avatar", "Avatar", "头像图标", 2},
                new Object[]{"1910000000000000103", "Star", "Star", "星标图标", 3},
                new Object[]{"1910000000000000104", "Medal", "Medal", "勋章图标", 4},
                new Object[]{"1910000000000000105", "Trophy", "Trophy", "奖杯图标", 5},
                new Object[]{"1910000000000000106", "Bell", "Bell", "铃铛图标", 6},
                new Object[]{"1910000000000000107", "Cherry", "Cherry", "樱桃图标", 7},
                new Object[]{"1910000000000000108", "MagicStick", "MagicStick", "魔法棒图标", 8}
        );
        for (Object[] icon : icons) {
            jdbcTemplate.update("""
                    INSERT INTO sys_icon (id, icon_name, component_name, description, sort, deleted, created_time, updated_time)
                    SELECT ?, ?, ?, ?, ?, 0, NOW(), NOW()
                    FROM DUAL
                    WHERE NOT EXISTS (SELECT 1 FROM sys_icon WHERE id = ?)
                    """, icon[0], icon[1], icon[2], icon[3], icon[4], icon[0]);
        }
    }

    private void initAdminUser() {
        jdbcTemplate.update("""
                INSERT INTO sys_user (id, name, gender, organization_id, email, password_hash, raw_password, avatar_icon_id, system_admin, sort, deleted, created_time, updated_time)
                SELECT ?, '王竞一', 1, ?, '632084210@qq.com', ?, 'Admin@123456', '1910000000000000102', 1, 0, 0, NOW(), NOW()
                FROM DUAL
                WHERE NOT EXISTS (SELECT 1 FROM sys_user WHERE email = '632084210@qq.com')
                """, ADMIN_USER_ID, DEFAULT_ORGANIZATION_ID, passwordUtils.encode("Admin@123456"));
        jdbcTemplate.update("""
                UPDATE sys_user
                SET name = '王竞一',
                    gender = 1,
                    organization_id = ?,
                    password_hash = ?,
                    raw_password = 'Admin@123456',
                    avatar_icon_id = '1910000000000000102',
                    system_admin = 1,
                    updated_time = NOW()
                WHERE email = '632084210@qq.com'
                """, DEFAULT_ORGANIZATION_ID, passwordUtils.encode("Admin@123456"));
    }

    private void initRoutes() {
        List<Object[]> routes = List.of(
                new Object[]{ROUTE_HOME_ID, "home", "/", "views/home/HomeView", "平台首页", "House", 0, 1},
                new Object[]{ROUTE_ORG_ID, "organizations", "/organizations", "views/organization/OrganizationView", "组织管理", "OfficeBuilding", 0, 2},
                new Object[]{ROUTE_PERMISSION_ID, "route-permissions", "/route-permissions", "views/permission/RoutePermissionView", "页面权限", "Menu", 0, 3},
                new Object[]{ROUTE_ASSIGN_ID, "permission-assign", "/permission-assign", "views/permission/PermissionAssignView", "组织赋权", "Checked", 0, 4},
                new Object[]{ROUTE_PROFILE_ID, "profile", "/profile", "views/profile/ProfileView", "个人中心", "User", 0, 5},
                new Object[]{ROUTE_USER_CENTER_ID, "user-management", "/user-management", "views/user/UserManagementView", "用户管理", "UserFilled", 1, 90}
        );
        for (Object[] route : routes) {
            jdbcTemplate.update("""
                    INSERT INTO sys_route_permission (id, route_name, route_path, component_path, title, icon, admin_only, sort, deleted, created_time, updated_time)
                    SELECT ?, ?, ?, ?, ?, ?, ?, ?, 0, NOW(), NOW()
                    FROM DUAL
                    WHERE NOT EXISTS (SELECT 1 FROM sys_route_permission WHERE id = ?)
                    """, route[0], route[1], route[2], route[3], route[4], route[5], route[6], route[7], route[0]);
            jdbcTemplate.update("""
                    UPDATE sys_route_permission
                    SET route_name = ?,
                        route_path = ?,
                        component_path = ?,
                        title = ?,
                        icon = ?,
                        admin_only = ?,
                        sort = ?,
                        updated_time = NOW()
                    WHERE id = ?
                    """, route[1], route[2], route[3], route[4], route[5], route[6], route[7], route[0]);
        }
    }

    private void initDefaultRelations() {
        for (String routeId : List.of(ROUTE_HOME_ID, ROUTE_ORG_ID, ROUTE_PERMISSION_ID, ROUTE_ASSIGN_ID, ROUTE_PROFILE_ID, ROUTE_USER_CENTER_ID)) {
            jdbcTemplate.update("""
                    INSERT INTO sys_organization_route_permission (id, organization_id, route_permission_id, sort, deleted, created_time, updated_time)
                    SELECT REPLACE(UUID(), '-', ''), ?, ?, 0, 0, NOW(), NOW()
                    FROM DUAL
                    WHERE NOT EXISTS (
                        SELECT 1 FROM sys_organization_route_permission
                        WHERE organization_id = ? AND route_permission_id = ?
                    )
                    """, DEFAULT_ORGANIZATION_ID, routeId, DEFAULT_ORGANIZATION_ID, routeId);
        }
    }
}
