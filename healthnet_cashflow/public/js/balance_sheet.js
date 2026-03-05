frappe.after_ajax(() => {

    let retryCount = 0;
    const maxRetries = 20;   // 6 seconds max
    const intervalTime = 300;

    const reportApiMap = {
        "Balance Sheet": {
            flag: "__balance_sheet_export_added",
            api: "healthnet_cashflow.api.balance_sheet_excel.export"
        },
        "Trial Balance": {
            flag: "__trial_balance_export_added",
            api: "healthnet_cashflow.api.trial_balance_excel.export"
        },
        "Profit and Loss Statement": {
            flag: "__profit_loss_export_added",
            api: "healthnet_cashflow.api.profit_loss_excel.export"
        },
        "Custom Cash Flow": {
            flag: "__cash_flow_export_added",
            api: "healthnet_cashflow.api.cash_flow_excel.export"
        }
    };

    const interval = setInterval(() => {

        retryCount++;

        if (retryCount >= maxRetries) {
            clearInterval(interval);
            return;
        }

        const report = frappe.query_report;
        if (!report || !report.report_name) return;

        const config = reportApiMap[report.report_name];
        if (!config) return;

        clearInterval(interval);

        // Prevent duplicate button
        if (report.page[config.flag]) return;
        report.page[config.flag] = true;

        report.page.add_menu_item(
            __("Export Excel"),
            () => {
                const url = "/api/method/" + config.api;
                window.open(url);
            }
        );

    }, intervalTime);

});