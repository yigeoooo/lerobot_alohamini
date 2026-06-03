package com.lerobot.saas.common.exception;

import com.lerobot.saas.common.api.ApiResponse;
import com.lerobot.saas.common.api.ResultCode;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.validation.BindException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public ApiResponse<Void> handleBusinessException(BusinessException ex, HttpServletRequest request) {
        log.warn("business exception, uri={}, message={}", request.getRequestURI(), ex.getMessage());
        return ApiResponse.fail(ex.getCode(), ex.getMessage());
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, BindException.class})
    public ApiResponse<Void> handleValidationException(Exception ex, HttpServletRequest request) {
        log.warn("validation exception, uri={}, message={}", request.getRequestURI(), ex.getMessage());
        return ApiResponse.fail(ResultCode.BAD_REQUEST.getCode(), "请求参数校验失败");
    }

    @ExceptionHandler(Exception.class)
    public ApiResponse<Void> handleException(Exception ex, HttpServletRequest request) {
        log.error("system exception, uri={}", request.getRequestURI(), ex);
        return ApiResponse.fail(ResultCode.INTERNAL_ERROR.getCode(), ResultCode.INTERNAL_ERROR.getMessage());
    }
}
