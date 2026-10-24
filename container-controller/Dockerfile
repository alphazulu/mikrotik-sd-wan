FROM scratch
COPY --chmod=0555 sdwan-controller /sdwan-controller
USER 65532:65532
ENTRYPOINT ["/sdwan-controller"]
CMD ["run", "/config/controller.json"]
