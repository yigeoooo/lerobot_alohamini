package com.lerobot.saas.common.interceptor;

import com.lerobot.saas.common.annotation.PublicAccess;
import com.lerobot.saas.common.api.ResultCode;
import com.lerobot.saas.common.context.UserContext;
import com.lerobot.saas.common.context.UserContextHolder;
import com.lerobot.saas.common.exception.BusinessException;
import com.lerobot.saas.common.util.JwtUtils;
import io.jsonwebtoken.Claims;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.annotation.AnnotationUtils;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public class AuthInterceptor implements HandlerInterceptor {

    private final JwtUtils jwtUtils;

    public AuthInterceptor(JwtUtils jwtUtils) {
        this.jwtUtils = jwtUtils;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        if (!(handler instanceof HandlerMethod handlerMethod)) {
            return true;
        }
        if (AnnotationUtils.findAnnotation(handlerMethod.getMethod(), PublicAccess.class) != null
                || AnnotationUtils.findAnnotation(handlerMethod.getBeanType(), PublicAccess.class) != null) {
            return true;
        }
        String authorization = request.getHeader("Authorization");
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            throw new BusinessException(ResultCode.UNAUTHORIZED);
        }
        String token = authorization.substring(7);
        Claims claims = jwtUtils.parseToken(token);
        UserContextHolder.set(new UserContext(
                claims.getSubject(),
                claims.get("organizationId", String.class),
                claims.get("systemAdmin", Boolean.class)
        ));
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        UserContextHolder.clear();
    }
}
