# syntax=docker/dockerfile:1.7
FROM maven:3.9.12-eclipse-temurin-21-alpine AS builder

WORKDIR /build
COPY pom.xml ./
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -q -DskipTests dependency:go-offline
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn -B -q package

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app
RUN addgroup -S gateway && adduser -S gateway -G gateway
COPY --from=builder /build/target/backend-gateway-0.1.0.jar /app/gateway.jar
USER gateway
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/gateway.jar"]
