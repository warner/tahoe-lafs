
function onDataReceived(data) {
    function console(text) {
        d3.select("#console").text(text);
        //$("#console").text("hi");// same
    }
    console("started");
    var timeline = d3.select("#timeline");
    var w = Number(timeline.style("width").slice(0,-2));
    // the SVG fills the width of the whole div, but it will extend
    // as far vertically as necessary (depends upon the data)
    var chart = timeline.append("svg:svg")
         .attr("id", "outer_chart")
         .attr("width", w)
         .attr("pointer-events", "all")
        .append("svg:g")
         .call(d3.behavior.zoom().on("zoom", redraw))
    ;
    // this "backboard" rect lets us catch mouse events anywhere in the
    // chart, even between the bars. Without it, we only see events on solid
    // objects like bars and text, but not in the gaps between.
    chart.append("svg:rect")
        .attr("id", "outer_rect")
        .attr("width", w).attr("height", 200).attr("fill", "none");

    // but the stuff we put inside it should have some room
    w = w-50;

    function reltime(t) {return t-data.bounds.min;}
    var last = data.bounds.max - data.bounds.min;
    //last = reltime(d3.max(data.dyhb, function(d){return d.finish_time;}));
    last = last * 1.05;
    // d3.time.scale() has no support for ms or us.
    var xOFF = d3.time.scale().domain([data.bounds.min, data.bounds.max])
                             .range([0,w]),
        x = d3.scale.linear().domain([-last*0.05, last])
                             .range([0,w]);
    function tx(d) { return "translate(" +x(d) + ",0)"; }
    function left(d) { return x(reltime(d.start_time)); }
    function right(d) {
        return d.finish_time ? x(reltime(d.finish_time)) : "1px";
    }
    function width(d) {
        return d.finish_time ? x(reltime(d.finish_time))-x(reltime(d.start_time)) : "1px";
    }
    function halfwidth(d) {
        if (d.finish_time)
            return (x(reltime(d.finish_time))-x(reltime(d.start_time)))/2;
        return "1px";
    }
    function middle(d) {
        if (d.finish_time)
            return (x(reltime(d.start_time))+x(reltime(d.finish_time)))/2;
        else
            return x(reltime(d.start_time)) + 1;
    }
    function color(d) { return data.server_info[d.serverid].color; }
    function servername(d) { return data.server_info[d.serverid].short; }
    function timeformat(duration) {
        // TODO: trim to microseconds, maybe humanize
        return duration;
    }

    var y = 0;
    chart.append("svg:text")
        .attr("x", "20px")
        .attr("y", y)
        .attr("text-anchor", "start") // anchor at top-left
        .attr("dy", ".71em")
        .attr("fill", "black")
        .text("DYHB requests");
    y += 20;

    // DYHB section
    var dyhb_y = d3.scale.ordinal()
                    .domain(d3.range(data.dyhb.length))
                    .rangeBands([y, y+data.dyhb.length*20], .2);
    y += data.dyhb.length*20;
    var dyhb = chart.selectAll("g.dyhb") // one per row
         .data(data.dyhb)
        .enter().append("svg:g")
         .attr("class", "dyhb")
         .attr("transform", function(d,i) {
                   return "translate("+x(reltime(d.start_time))+","
                       +dyhb_y(i)+")";
               })
    ;
    dyhb.append("svg:rect")
         .attr("width", width)
         .attr("height", dyhb_y.rangeBand())
         .attr("stroke", "black")
         .attr("fill", color)
         .attr("title", function(d){return "shnums: "+d.response_shnums;})
    ;
    dyhb.append("svg:text")
         .attr("text-anchor", "end")
         .attr("fill", "#444")
         .attr("x", "-0.3em") // for some reason dx doesn't work
         .attr("dy", "1.0em")
         .attr("font-size", "12px")
         .text(servername)
    ;
    var dyhb_rightboxes = dyhb.append("svg:g")
         .attr("class", "rightbox")
         .attr("transform", function(d) {return "translate("+width(d)
                                         +",0)";})
    ;
    dyhb_rightboxes.append("svg:text")
         .attr("text-anchor", "start")
         .attr("y", dyhb_y.rangeBand())
         .attr("dx", "0.5em")
         .attr("dy", "-0.4em")
         .attr("fill", "#444")
         .attr("font-size", "14px")
         .text(function (d) {return "shnums: "+d.response_shnums;})
    ;

    // read() requests
    chart.append("svg:text")
        .attr("x", "20px")
        .attr("y", y)
        .attr("text-anchor", "start") // anchor at top-left
        .attr("dy", ".71em")
        .attr("fill", "black")
        .text("read() requests");
    y += 20;
    var read = chart.selectAll("g.read")
         .data(data.read)
        .enter().append("svg:g")
         .attr("class", "read")
         .attr("transform", function(d) {
                   return "translate("+left(d)+","+(y+30*d.row)+")"; })
    ;
    y += 30*(1+d3.max(data.read, function(d){return d.row;}));
    read.append("svg:rect")
         .attr("width", width)
         .attr("height", 20)
         .attr("fill", "red")
         .attr("stroke", "black")
         .attr("title", function(d)
               {return "read(start="+d.start+", len="+d.length+") -> "
                +d.bytes_returned+" bytes";})
    ;
    read.append("svg:text")
         .attr("x", middle)
         .attr("dy", "0.9em")
         .attr("fill", "black")
         .text(function(d) {return "["+d.start+":+"+d.length+"]";})
    ;

    // segment requests
    chart.append("svg:text")
        .attr("x", "20px")
        .attr("y", y)
        .attr("text-anchor", "start") // anchor at top-left
        .attr("dy", ".71em")
        .attr("fill", "black")
        .text("segment() requests");
    y += 20;
    var segment = chart.selectAll("g.segment")
         .data(data.segment)
        .enter().append("svg:g")
         .attr("class", "segment")
         .attr("transform", function(d) {
                   return "translate("+left(d)+","+(y+30*d.row)+")"; })
    ;
    y += 30*(1+d3.max(data.segment, function(d){return d.row;}));
    segment.append("svg:rect")
         .attr("width", width)
         .attr("height", 20)
         .attr("fill", function(d){return d.success ? "#cfc" : "#fcc";})
         .attr("stroke", "black")
         .attr("stroke-width", 1)
         .attr("title", function(d) {
                   return "seg"+d.segment_number+" ["+d.segment_start
                       +":+"+d.segment_length+"] (took "
                       +timeformat(d.finish_time-d.start_time)+")";})
    ;
    segment.append("svg:text")
         .attr("x", halfwidth)
         .attr("text-anchor", "middle")
         .attr("dy", "0.9em")
         .attr("fill", "black")
         .text(function(d) {return d.segment_number;})
    ;

    var shnum_colors = d3.scale.category10();

    // block requests
    chart.append("svg:text")
        .attr("x", "20px")
        .attr("y", y)
        .attr("text-anchor", "start") // anchor at top-left
        .attr("dy", ".71em")
        .attr("fill", "black")
        .text("block() requests");
    y += 20;
    var block_row_to_y = {};
    var dummy = function() {
        var row_y=y;
        for (var group=0; group < data.block_rownums.length; group++) {
            for (var row=0; row < data.block_rownums[group]; row++) {
                block_row_to_y[group+"-"+row] = row_y;
                row_y += 12; y += 12;
            }
            row_y += 5; y += 5;
        }
    }();
    var blocks = chart.selectAll("g.block")
         .data(data.block)
        .enter().append("svg:g")
         .attr("class", "block")
         .attr("transform", function(d) {
                   var ry = block_row_to_y[d.row[0]+"-"+d.row[1]];
                   return "translate("+left(d)+"," +ry+")"; })
    ;
    // everything appended to blocks starts at the top-left of the
    // correct per-rect location
    blocks.append("svg:rect")
         .attr("width", width)
         .attr("y", function(d) {return (d.response_length > 100) ? 0:3;})
         .attr("height",
               function(d) {return (d.response_length > 100) ? 10:4;})
         .attr("fill", color)
         .attr("stroke", function(d){return shnum_colors(d.shnum);})
         .attr("stroke-width", 1)
         .attr("title", function(d){
                   return "sh"+d.shnum+"-on-"+d.serverid.slice(0,4)
                       +" ["+d.start+":+"+d.length+"] -> "
                       +d.response_length;})
    ;
    blocks.append("svg:text")
         .attr("x", halfwidth)
         .attr("dy", "0.9em")
         .attr("fill", "black")
         .attr("font-size", "8px")
         .attr("text-anchor", "middle")
         .text(function(d) {return "sh"+d.shnum;})
    ;

    var count=0;
    redraw();
    function redraw() {
        console("redraw "+count);
        count += 1;

        if (d3.event) d3.event.transform(x);

        // horizontal scale markers: vertical lines at rational timestamps
        var rules = chart.selectAll("g.rule")
            .data(x.ticks(10))//, String)
            .attr("transform", tx);
        rules.select("text").text(x.tickFormat(10));

        var newrules = rules.enter().insert("svg:g")
              .attr("class", "rule")
              .attr("transform", tx)
        ;

        newrules.append("svg:line")
            .attr("y1", y)
            .attr("y2", y + 6)
            .attr("stroke", "black");
        newrules.append("svg:line")
            .attr("y1", 0)
            .attr("y2", y)
            .attr("stroke", "black")
            .attr("stroke-opacity", .3);
        newrules.append("svg:text")
            .attr("y", y + 9)
            .attr("dy", ".71em")
            .attr("text-anchor", "middle")
            .attr("fill", "black")
            .text(x.tickFormat(10));
        rules.exit().remove();
    }
    chart.append("svg:text")
        .attr("x", w/2)
        .attr("y", y + 35)
        .attr("text-anchor", "middle")
        .attr("fill", "black")
        .text("seconds");
    y += 45;

    d3.select("#outer_chart").attr("height", y);
    d3.select("#outer_rect").attr("height", y);

    return;
}


function unused() {
    var bounds = { min: data.bounds.min,
                   max: data.bounds.max
                 };
    //bounds.max = data.dyhb[data.dyhb.length-1].finish_time;
    var duration = bounds.max - bounds.min;
    var WIDTH = 600;
    var vis = new pv.Panel().canvas("timeline").margin(30);

    var dyhb_top = 0;
    var read_top = dyhb_top + 30*data.dyhb[data.dyhb.length-1].row+60;
    var segment_top = read_top + 30*data.read[data.read.length-1].row+60;
    var block_top = segment_top + 30*data.segment[data.segment.length-1].row+60;
    var block_row_to_y = {};
    var row_y=0;
    for (var group=0; group < data.block_rownums.length; group++) {
        for (var row=0; row < data.block_rownums[group]; row++) {
            block_row_to_y[group+"-"+row] = row_y;
            row_y += 10;
        }
        row_y += 5;
    }

    var height = block_top + row_y;
    var kx = bounds.min;
    var ky = 1;
    var x = pv.Scale.linear(bounds.min, bounds.max).range(0, WIDTH-40);
    var relx = pv.Scale.linear(0, duration).range(0, WIDTH-40);
    //var y = pv.Scale.linear(-ky,ky).range(0, height);
    //x.nice(); relx.nice();

    /* add the invisible panel now, at the bottom of the stack, so that
    it won't steal mouseover events and prevent tooltips from
    working. */
    var zoomer = vis.add(pv.Panel)
        .events("all")
        .event("mousedown", pv.Behavior.pan())
        .event("mousewheel", pv.Behavior.zoom())
        .event("pan", transform)
        .event("zoom", transform)
    ;

    vis.anchor("top").top(-20).add(pv.Label).text("DYHB Requests");

    /* we use a function for data=relx.ticks() here instead of
     simply .data(relx.ticks()) so that it will be recalculated when
     the scales change (by pan/zoom) */
    var xaxis = vis.add(pv.Rule)
        .data(function() {return relx.ticks();})
        .strokeStyle("#ccc")
        .left(relx)
        .anchor("bottom").add(pv.Label)
        .text(function(d){return relx.tickFormat(d)+"s";});


    vis.height(height);

    function zoomin() {
        var t = zoomer.transform().invert();
        t.k = t.k/1.5;
        zoomer.transform(t.invert());
        zoompan(t);
    }

    function zoomout() {
        var t = zoomer.transform().invert();
        t.k = t.k*1.5;
        zoomer.transform(t.invert());
        zoompan(t);
    }

    function transform() {
        var t = this.transform().invert();
        zoompan(t);
    }
    function zoompan(t) {
        // when t.x=0 and t.k=1.0, left should be bounds.min
        x.domain(bounds.min + (t.x/WIDTH)*duration,
                 bounds.min + t.k*duration + (t.x/WIDTH)*duration);
        relx.domain(0 + t.x/WIDTH*duration,
                    t.k*duration + (t.x/WIDTH)*duration);
        vis.render();
    }

    vis.render();
    $("#zoomin").click(zoomin);
    $("#zoomout").click(zoomout);
}

$(function() {

      $.ajax({url: "event_json",
              method: 'GET',
              dataType: 'json',
              success: onDataReceived });
});

