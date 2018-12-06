var network;
var authors;
var base_data;
var all_nodes;
var all_edges;
var num_nodes = 0;

function focus_on_node(cur_authors) {
    var found = false;
    var focused = false;
    var found_authors = [];
    for( i=0; i < cur_authors.length; i++) {
        if (authors.indexOf(cur_authors[i].name) >= 0) {
            if (!focused) {
                network.focus(cur_authors[i].name, {animation: true, scale: 1});
                focused = true;
            }
            found_authors.push(cur_authors[i].name);
            found = true;
        }
    }
    if (found) {
        network.selectNodes(found_authors);
    } else {
        alert('Author/s not found');
    }
}

function draw_network(data) {
    all_nodes = new vis.DataSet(data['nodes']);
    num_nodes = all_nodes.length;
    // create an array with edges
    all_edges = new vis.DataSet(data['edges']);

    // create a network
    var container = document.getElementById('mynetwork');

    // provide the data in the vis format
    var graph_data = {
        nodes: all_nodes,
        edges: all_edges
    };
    var options = {
        layout: {
            improvedLayout: false
        },
        nodes: {
            shape: 'dot',
            scaling: { min: 7,max: 50, label: false },
            font: {size: 14, face: 'Helvetica Neue, Helvetica, Arial'},
        },
        edges: {
            color: {
                color: 'rgba(50, 133, 236, 0.3)',
                highlight:'#c107fb',
            },
            smooth: false,

        },
        physics: {
            enabled: false,
            stabilization: {
              enabled: false,
              iterations: 50,
              updateInterval: 100,
              onlyDynamicEdges: false,
              fit: true
            },
            solver: 'forceAtlas2Based',
            forceAtlas2Based: {
                avoidOverlap: 1
            }
        }
    };

    // initialize your network!
    network = new vis.Network(container, graph_data, options);
    network.on("selectNode", function(params) {
        var sel_nodes = network.getSelectedNodes();
        $.get('/author_papers', {q: JSON.stringify(sel_nodes)}, function(res) {
            var papers = '';
            res.map(function(cur_p) {
                papers += `<div class='papers-list-item'><a href=${cur_p.url}>${cur_p.title}</a></div>`
            });

            $('#papers_list .author_name').text(`${sel_nodes[0]}`);
            $('#papers_list').show();
            $('#papers_list .content').html(papers);
        });
//      if (params.nodes.length == 1) {
//          if (network.isCluster(params.nodes[0]) == true) {
//              network.openCluster(params.nodes[0]);
//          }
//      }
    });
}

$.getJSON("static/authors.json", function (data) {
    console.log('Network graph was downloaded');
    base_data = data;
    draw_network(data);

    var input = document.getElementById("searchInput");
    authors = Array.from(data.nodes, function(d){ return(d.id) });

});

$.get('/categories', function(res) {
    var options = '';
    $(res).each(function(index, item){ //loop through your elements
        if((item.key !== 'cs.CV') & (item.key !== 'cs.CL')){ //check the company
            options += `<a class="dropdown-item" href="#" value="${item.key}">${item.value}</a>`
        }
    });
    $('#categories_dropdown').append(options);
});

$("#categories_dropdown").on('click', '.dropdown-item', function(){
    $("#categories_button").text($(this).text());
    var val = $(this).attr('value');
    if (val === 'All') {
        var cur_nodes = all_nodes;
    }
    else {
        var cur_nodes = all_nodes.get({
          filter: function (item) {
            return item.fields.indexOf(val) >= 0;
          }
        });
    }
    num_nodes = cur_nodes.length;
    network.setData({nodes: cur_nodes, edges: all_edges});
});

$('#redraw').on('click', function(e) {
    if (num_nodes > 200) {
        alert('This feature is too slow for over 200 nodes');
        return;
    }
    $('body').addClass('dark');
    $('.spinner').show();
    network.stabilize();
    network.on('stabilized', function() {
        $('body').removeClass('dark');
        $('.spinner').hide();
        setTimeout(function(){ network.fit(); }, 10);

    });
});

var options = {
    url: function(phrase) {
        return "/autocomplete?q=" + phrase;
    },
    getValue: "name",
    list: {
		onClickEvent: function() {
		    var cur_s = $("#searchInput").getSelectedItemData();
		    console.log(cur_s);
		    if (cur_s.type === 'author') {
                focus_on_node([cur_s]);
		    } else { // paper
                focus_on_node(cur_s.authors);
		    }
		},
		maxNumberOfElements: 10,
		match: {
			enabled: true
		},
		requestDelay: 100
	},
	template: {
		type: "custom",
		method: function(value, item) {
		    var icon = (item.type === 'paper' ? 'newspaper' : 'user');
			return `<i class="fas fa-${icon}"></i> ${item.name}`
		}
	}

};
$("#searchInput").easyAutocomplete(options);

$('#searchInput').on('keypress', function(e) {
  if (e.which == 13) {
    var name = this.value.toLowerCase().split(' ').map((s) => s.charAt(0).toUpperCase() + s.substring(1)).join(' ');
    focus_on_node([{name: name}]);
    return false;    //<---- Add this line
  }
});

$('#reset_zoom').on('click', function(e) { network.fit()});

$('.collapse-expand').on('click', function(e) {
    $('#papers_list .content').toggle();
    $('.collapse-expand i').toggleClass('fa-minus');
    $('.collapse-expand i').toggleClass('fa-plus');
});