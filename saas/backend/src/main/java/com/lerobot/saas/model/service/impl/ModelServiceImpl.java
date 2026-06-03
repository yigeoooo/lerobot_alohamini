package com.lerobot.saas.model.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lerobot.saas.common.api.ResultCode;
import com.lerobot.saas.common.context.UserContext;
import com.lerobot.saas.common.context.UserContextHolder;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.common.properties.PolicyProperties;
import com.lerobot.saas.model.dao.ModelDao;
import com.lerobot.saas.model.dto.ModelSaveRequest;
import com.lerobot.saas.model.entity.SysModel;
import com.lerobot.saas.model.service.ModelService;
import com.lerobot.saas.model.vo.ModelVO;
import com.lerobot.saas.model.vo.PolicyDirectoryVO;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
public class ModelServiceImpl implements ModelService {

    private final ModelDao modelDao;
    private final PolicyProperties policyProperties;

    public ModelServiceImpl(ModelDao modelDao, PolicyProperties policyProperties) {
        this.modelDao = modelDao;
        this.policyProperties = policyProperties;
    }

    @Override
    public List<PolicyDirectoryVO> listPolicyDirectories() {
        Path policyRoot = resolvePolicyRoot();
        if (!Files.isDirectory(policyRoot)) {
            throw new BusinessException("策略目录不存在: " + policyRoot);
        }

        try (Stream<Path> stream = Files.list(policyRoot)) {
            return stream
                    .filter(Files::isDirectory)
                    .map(path -> new PolicyDirectoryVO(path.getFileName().toString()))
                    .sorted(Comparator.comparing(PolicyDirectoryVO::getPolicyCode))
                    .toList();
        } catch (IOException e) {
            throw new BusinessException("读取策略目录失败");
        }
    }

    @Override
    public List<ModelVO> listModels() {
        return modelDao.selectList(new LambdaQueryWrapper<SysModel>()
                        .orderByAsc(SysModel::getSort)
                        .orderByAsc(SysModel::getCreatedTime))
                .stream()
                .map(this::toVO)
                .toList();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createModel(ModelSaveRequest request) {
        requireAdmin();
        validatePolicyCode(request.getModelCode());
        assertModelCodeAvailable(request.getModelCode(), null);

        SysModel model = new SysModel();
        model.setModelCode(request.getModelCode().trim());
        model.setModelName(request.getModelName().trim());
        model.setSort(request.getSort());
        modelDao.insert(model);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateModel(String modelId, ModelSaveRequest request) {
        requireAdmin();
        SysModel model = requireModel(modelId);
        validatePolicyCode(request.getModelCode());
        assertModelCodeAvailable(request.getModelCode(), modelId);

        model.setModelCode(request.getModelCode().trim());
        model.setModelName(request.getModelName().trim());
        model.setSort(request.getSort());
        modelDao.updateById(model);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteModel(String modelId) {
        requireAdmin();
        requireModel(modelId);
        modelDao.deleteById(modelId);
    }

    private void requireAdmin() {
        UserContext userContext = UserContextHolder.get();
        if (userContext == null) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        if (!Boolean.TRUE.equals(userContext.getSystemAdmin())) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }

    private SysModel requireModel(String modelId) {
        SysModel model = modelDao.selectById(modelId);
        if (model == null) {
            throw new BusinessException("模型不存在");
        }
        return model;
    }

    private void validatePolicyCode(String modelCode) {
        if (!StringUtils.hasText(modelCode)) {
            throw new BusinessException("模型编码不能为空");
        }
        Set<String> availableCodes = listPolicyDirectories().stream()
                .map(PolicyDirectoryVO::getPolicyCode)
                .collect(Collectors.toSet());
        if (!availableCodes.contains(modelCode.trim())) {
            throw new BusinessException("模型编码不在当前策略目录中");
        }
    }

    private void assertModelCodeAvailable(String modelCode, String excludeModelId) {
        Long count = modelDao.selectCount(new LambdaQueryWrapper<SysModel>()
                .eq(SysModel::getModelCode, modelCode.trim())
                .ne(StringUtils.hasText(excludeModelId), SysModel::getId, excludeModelId));
        if (count != null && count > 0) {
            throw new BusinessException("模型编码已存在");
        }
    }

    private Path resolvePolicyRoot() {
        String configuredPath = StringUtils.hasText(policyProperties.scanPath())
                ? policyProperties.scanPath().trim()
                : "src/lerobot/policies";
        Path rawPath = Paths.get(configuredPath);
        if (rawPath.isAbsolute()) {
            return rawPath.normalize();
        }

        Path cwd = Paths.get("").toAbsolutePath().normalize();
        List<Path> candidates = new ArrayList<>();
        candidates.add(cwd.resolve(rawPath).normalize());
        candidates.add(cwd.resolve("..").resolve(rawPath).normalize());
        candidates.add(cwd.resolve("..").resolve("..").resolve(rawPath).normalize());
        for (Path candidate : candidates) {
            if (Files.isDirectory(candidate)) {
                return candidate;
            }
        }
        return candidates.get(0);
    }

    private ModelVO toVO(SysModel model) {
        return new ModelVO(
                model.getId(),
                model.getModelCode(),
                model.getModelName(),
                model.getSort(),
                model.getCreatedTime(),
                model.getUpdatedTime()
        );
    }
}
