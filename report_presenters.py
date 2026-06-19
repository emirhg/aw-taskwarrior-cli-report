class HierarchicalReport:
    def __init__(self, render_func):
        self.render_func = render_func

    def present(self, report_data, **kwargs):
        return self.render_func(report_data, **kwargs)


class TimelineReport:
    def __init__(self, render_func):
        self.render_func = render_func

    def present(self, slots, **kwargs):
        return self.render_func(slots, **kwargs)
