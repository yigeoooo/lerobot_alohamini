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
    private static final String ROUTE_DATASET_ID = "1910000000000000017";
    private static final String ROUTE_MODEL_ID = "1910000000000000018";
    private static final String ROUTE_TRAINING_ID = "1910000000000000019";

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
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_dataset (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    dataset_name VARCHAR(150) NOT NULL,
                    organization_id VARCHAR(32) NOT NULL,
                    user_id VARCHAR(32) NOT NULL,
                    original_file_name VARCHAR(255) NOT NULL,
                    storage_path VARCHAR(500) NOT NULL,
                    upload_status VARCHAR(32) NOT NULL,
                    error_message VARCHAR(500) NULL,
                    codebase_version VARCHAR(50) NULL,
                    robot_type VARCHAR(100) NULL,
                    total_episodes INT NULL,
                    total_frames BIGINT NULL,
                    total_tasks INT NULL,
                    fps INT NULL,
                    data_files_size_mb DECIMAL(10,2) NULL,
                    video_files_size_mb DECIMAL(10,2) NULL,
                    feature_count INT NULL,
                    camera_count INT NULL,
                    feature_keys TEXT NULL,
                    camera_keys TEXT NULL,
                    metadata_json LONGTEXT NULL,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_model (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    model_code VARCHAR(100) NOT NULL,
                    model_name VARCHAR(150) NOT NULL,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS sys_train_task (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    task_name VARCHAR(150) NOT NULL,
                    organization_id VARCHAR(32) NOT NULL,
                    user_id VARCHAR(32) NOT NULL,
                    dataset_id VARCHAR(32) NOT NULL,
                    dataset_name VARCHAR(150) NOT NULL,
                    dataset_path VARCHAR(500) NOT NULL,
                    model_id VARCHAR(32) NOT NULL,
                    model_code VARCHAR(100) NOT NULL,
                    model_name VARCHAR(150) NOT NULL,
                    output_dir VARCHAR(500) NOT NULL,
                    policy_repo_id VARCHAR(200) NOT NULL,
                    device VARCHAR(50) NULL,
                    wandb_enable TINYINT NULL,
                    steps INT NULL,
                    batch_size INT NULL,
                    use_amp TINYINT NULL,
                    optimizer_type VARCHAR(50) NULL,
                    optimizer_lr VARCHAR(50) NULL,
                    optimizer_weight_decay VARCHAR(50) NULL,
                    optimizer_grad_clip_norm VARCHAR(50) NULL,
                    log_freq INT NULL,
                    save_freq INT NULL,
                    policy_chunk_size INT NULL,
                    policy_action_steps INT NULL,
                    task_status VARCHAR(32) NOT NULL,
                    process_id BIGINT NULL,
                    command_text LONGTEXT NULL,
                    log_path VARCHAR(500) NULL,
                    exit_code INT NULL,
                    error_message VARCHAR(1000) NULL,
                    sort INT NOT NULL DEFAULT 0,
                    deleted TINYINT NOT NULL DEFAULT 0,
                    created_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """);
    }

    private void syncColumns() {
        ensureBaseColumns("sys_organization");
        ensureBaseColumns("sys_icon");
        ensureBaseColumns("sys_user");
        ensureBaseColumns("sys_route_permission");
        ensureBaseColumns("sys_organization_route_permission");
        ensureBaseColumns("sys_dataset");
        ensureBaseColumns("sys_model");
        ensureBaseColumns("sys_train_task");

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

        ensureColumn("sys_dataset", "dataset_name", "VARCHAR(150) NOT NULL");
        ensureColumn("sys_dataset", "organization_id", "VARCHAR(32) NOT NULL AFTER dataset_name");
        ensureColumn("sys_dataset", "user_id", "VARCHAR(32) NOT NULL AFTER organization_id");
        ensureColumn("sys_dataset", "original_file_name", "VARCHAR(255) NOT NULL AFTER user_id");
        ensureColumn("sys_dataset", "storage_path", "VARCHAR(500) NOT NULL AFTER original_file_name");
        ensureColumn("sys_dataset", "upload_status", "VARCHAR(32) NOT NULL AFTER storage_path");
        ensureColumn("sys_dataset", "error_message", "VARCHAR(500) NULL AFTER upload_status");
        ensureColumn("sys_dataset", "codebase_version", "VARCHAR(50) NULL AFTER error_message");
        ensureColumn("sys_dataset", "robot_type", "VARCHAR(100) NULL AFTER codebase_version");
        ensureColumn("sys_dataset", "total_episodes", "INT NULL AFTER robot_type");
        ensureColumn("sys_dataset", "total_frames", "BIGINT NULL AFTER total_episodes");
        ensureColumn("sys_dataset", "total_tasks", "INT NULL AFTER total_frames");
        ensureColumn("sys_dataset", "fps", "INT NULL AFTER total_tasks");
        ensureColumn("sys_dataset", "data_files_size_mb", "DECIMAL(10,2) NULL AFTER fps");
        ensureColumn("sys_dataset", "video_files_size_mb", "DECIMAL(10,2) NULL AFTER data_files_size_mb");
        ensureColumn("sys_dataset", "feature_count", "INT NULL AFTER video_files_size_mb");
        ensureColumn("sys_dataset", "camera_count", "INT NULL AFTER feature_count");
        ensureColumn("sys_dataset", "feature_keys", "TEXT NULL AFTER camera_count");
        ensureColumn("sys_dataset", "camera_keys", "TEXT NULL AFTER feature_keys");
        ensureColumn("sys_dataset", "metadata_json", "LONGTEXT NULL AFTER camera_keys");

        ensureColumn("sys_model", "model_code", "VARCHAR(100) NOT NULL");
        ensureColumn("sys_model", "model_name", "VARCHAR(150) NOT NULL AFTER model_code");

        ensureColumn("sys_train_task", "task_name", "VARCHAR(150) NOT NULL");
        ensureColumn("sys_train_task", "organization_id", "VARCHAR(32) NOT NULL AFTER task_name");
        ensureColumn("sys_train_task", "user_id", "VARCHAR(32) NOT NULL AFTER organization_id");
        ensureColumn("sys_train_task", "dataset_id", "VARCHAR(32) NOT NULL AFTER user_id");
        ensureColumn("sys_train_task", "dataset_name", "VARCHAR(150) NOT NULL AFTER dataset_id");
        ensureColumn("sys_train_task", "dataset_path", "VARCHAR(500) NOT NULL AFTER dataset_name");
        ensureColumn("sys_train_task", "model_id", "VARCHAR(32) NOT NULL AFTER dataset_path");
        ensureColumn("sys_train_task", "model_code", "VARCHAR(100) NOT NULL AFTER model_id");
        ensureColumn("sys_train_task", "model_name", "VARCHAR(150) NOT NULL AFTER model_code");
        ensureColumn("sys_train_task", "output_dir", "VARCHAR(500) NOT NULL AFTER model_name");
        ensureColumn("sys_train_task", "policy_repo_id", "VARCHAR(200) NOT NULL AFTER output_dir");
        ensureColumn("sys_train_task", "device", "VARCHAR(50) NULL AFTER policy_repo_id");
        ensureColumn("sys_train_task", "wandb_enable", "TINYINT NULL AFTER device");
        ensureColumn("sys_train_task", "steps", "INT NULL AFTER wandb_enable");
        ensureColumn("sys_train_task", "batch_size", "INT NULL AFTER steps");
        ensureColumn("sys_train_task", "use_amp", "TINYINT NULL AFTER batch_size");
        ensureColumn("sys_train_task", "optimizer_type", "VARCHAR(50) NULL AFTER use_amp");
        ensureColumn("sys_train_task", "optimizer_lr", "VARCHAR(50) NULL AFTER optimizer_type");
        ensureColumn("sys_train_task", "optimizer_weight_decay", "VARCHAR(50) NULL AFTER optimizer_lr");
        ensureColumn("sys_train_task", "optimizer_grad_clip_norm", "VARCHAR(50) NULL AFTER optimizer_weight_decay");
        ensureColumn("sys_train_task", "log_freq", "INT NULL AFTER optimizer_grad_clip_norm");
        ensureColumn("sys_train_task", "save_freq", "INT NULL AFTER log_freq");
        ensureColumn("sys_train_task", "policy_chunk_size", "INT NULL AFTER save_freq");
        ensureColumn("sys_train_task", "policy_action_steps", "INT NULL AFTER policy_chunk_size");
        ensureColumn("sys_train_task", "task_status", "VARCHAR(32) NOT NULL AFTER policy_action_steps");
        ensureColumn("sys_train_task", "process_id", "BIGINT NULL AFTER task_status");
        ensureColumn("sys_train_task", "command_text", "LONGTEXT NULL AFTER process_id");
        ensureColumn("sys_train_task", "log_path", "VARCHAR(500) NULL AFTER command_text");
        ensureColumn("sys_train_task", "exit_code", "INT NULL AFTER log_path");
        ensureColumn("sys_train_task", "error_message", "VARCHAR(1000) NULL AFTER exit_code");
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
                new Object[]{ROUTE_DATASET_ID, "dataset-upload", "/datasets", "views/dataset/DatasetUploadView", "数据集上传", "UploadFilled", 0, 6},
                new Object[]{ROUTE_MODEL_ID, "model-management", "/models", "views/model/ModelManagementView", "模型管理", "Cpu", 1, 7},
                new Object[]{ROUTE_TRAINING_ID, "training-tasks", "/training-tasks", "views/training/TrainingTaskView", "模型训练", "TrendCharts", 0, 8},
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
        for (String routeId : List.of(ROUTE_HOME_ID, ROUTE_ORG_ID, ROUTE_PERMISSION_ID, ROUTE_ASSIGN_ID, ROUTE_PROFILE_ID, ROUTE_DATASET_ID, ROUTE_MODEL_ID, ROUTE_TRAINING_ID, ROUTE_USER_CENTER_ID)) {
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
