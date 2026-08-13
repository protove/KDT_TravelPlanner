# syntax=docker/dockerfile:1.7

FROM eclipse-temurin:21-jdk-alpine AS base
WORKDIR /app
RUN addgroup -S -g 10001 spring \
    && adduser -S -D -H -u 10001 -G spring spring \
    && mkdir -p /app/logs \
    && chown -R spring:spring /app/logs
COPY gradle ./gradle
COPY gradlew gradlew.bat build.gradle.kts settings.gradle.kts ./
RUN chmod +x gradlew

FROM base AS dev
COPY . .
RUN chmod +x gradlew docker/dev-entrypoint.sh
EXPOSE 8080
CMD ["./docker/dev-entrypoint.sh"]

FROM base AS builder
COPY src ./src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine AS runner
WORKDIR /app

RUN addgroup -S -g 10001 spring \
    && adduser -S -D -H -u 10001 -G spring spring \
    && mkdir -p /app/logs \
    && chown -R spring:spring /app/logs

COPY --from=builder --chown=spring:spring /app/build/libs/app.jar ./app.jar

USER spring
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]