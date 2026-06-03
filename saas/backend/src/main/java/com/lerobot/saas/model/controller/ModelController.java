package com.lerobot.saas.model.controller;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.model.dto.ModelSaveRequest;
import com.lerobot.saas.model.service.ModelService;
import com.lerobot.saas.model.vo.ModelVO;
import com.lerobot.saas.model.vo.PolicyDirectoryVO;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/models")
public class ModelController {

    private final ModelService modelService;

    public ModelController(ModelService modelService) {
        this.modelService = modelService;
    }

    @GetMapping("/policies")
    public ApiResponse<List<PolicyDirectoryVO>> listPolicies() {
        return ApiResponse.success(modelService.listPolicyDirectories());
    }

    @GetMapping
    public ApiResponse<List<ModelVO>> listModels() {
        return ApiResponse.success(modelService.listModels());
    }

    @PostMapping
    public ApiResponse<Void> create(@Valid @RequestBody ModelSaveRequest request) {
        modelService.createModel(request);
        return ApiResponse.success("模型创建成功", null);
    }

    @PutMapping("/{modelId}")
    public ApiResponse<Void> update(@PathVariable String modelId,
                                    @Valid @RequestBody ModelSaveRequest request) {
        modelService.updateModel(modelId, request);
        return ApiResponse.success("模型更新成功", null);
    }

    @DeleteMapping("/{modelId}")
    public ApiResponse<Void> delete(@PathVariable String modelId) {
        modelService.deleteModel(modelId);
        return ApiResponse.success("模型删除成功", null);
    }
}
