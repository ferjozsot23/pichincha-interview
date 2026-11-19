FROM public.ecr.aws/lambda/python:3.13

RUN pip install --no-cache-dir uv==0.11.19

# Dependencies first (cached layer), installed from the lockfile into the Lambda task root.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt \
    && uv pip install --no-cache --python /var/lang/bin/python3 --target "${LAMBDA_TASK_ROOT}" -r requirements.txt \
    && rm requirements.txt

COPY src/onboarding_agent ${LAMBDA_TASK_ROOT}/onboarding_agent

CMD ["onboarding_agent.lambda_handler.handler"]
